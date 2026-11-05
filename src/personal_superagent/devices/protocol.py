"""出站轮询协议：不重领未知结果；先锁任务再锁操作，与取消保持相同顺序。"""

import secrets
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from personal_superagent.execution.models import Attempt
from personal_superagent.tasks.models import Task
from .auth import digest
from .models import Device, Grant, LocalOperation

TOOLS = {"list_files", "read_text", "write_text"}
TERMINAL = {"succeeded", "failed"}


def sync_grants(device, manifest):
    if not isinstance(manifest, list) or len(manifest) > 16:
        raise ValueError("最多授权 16 个目录")
    ids = []
    for item in manifest:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("授权结构不合法")
        grant_id = uuid.UUID(item["id"])
        label, tools = item.get("label", ""), item.get("tools", [])
        if (
            not isinstance(label, str)
            or not 1 <= len(label) <= 80
            or not isinstance(tools, list)
            or not set(tools) <= TOOLS
        ):
            raise ValueError("授权名称或工具不合法")
        if set(item) != {"id", "label", "tools"}:
            raise ValueError("协议不接受本地绝对路径等额外字段")
        if Grant.objects.filter(pk=grant_id).exclude(device=device).exists():
            raise ValueError("授权 ID 不属于该设备")
        grant, _ = Grant.objects.get_or_create(
            pk=grant_id,
            device=device,
            defaults={"label": label, "tools": sorted(tools)},
        )
        if (
            grant.label != label
            or grant.tools != sorted(tools)
            or not grant.local_enabled
        ):
            grant.label, grant.tools, grant.local_enabled = label, sorted(tools), True
            grant.revision += 1
            grant.save(update_fields=["label", "tools", "local_enabled", "revision"])
        ids.append(grant_id)
    for grant in device.grants.exclude(pk__in=ids).filter(local_enabled=True):
        grant.local_enabled = False
        grant.revision += 1
        grant.save(update_fields=["local_enabled", "revision"])


def allowed(operation) -> bool:
    grant = operation.grant
    return (
        not grant.device.revoked_at
        and not grant.revoked_at
        and grant.local_enabled
        and grant.revision == operation.grant_revision
        and operation.tool in grant.tools
    )


@transaction.atomic
def poll(device_id, session, manifest, *, connect=False):
    device = Device.objects.select_for_update().get(pk=device_id, revoked_at=None)
    if connect:
        device.session = session
    if device.session != session:
        raise ValueError("设备会话已被另一个客户端替代，请检查重复运行")
    sync_grants(device, manifest)
    device.last_seen = timezone.now()
    device.save(update_fields=["last_seen", "session"])
    operation = (
        LocalOperation.objects.select_for_update(skip_locked=True)
        .filter(
            grant__device=device,
            state="pending",
            attempt__state__in=["waiting_device", "waiting_approval"],
        )
        .order_by("created_at")
        .first()
    )
    result = {
        "operation": None,
        "grants": list(
            device.grants.values("id", "revision", "revoked_at", "local_enabled")
        ),
    }
    if operation:
        if not allowed(operation):
            operation.state, operation.reason = (
                "failed",
                "目录或工具授权已改变，操作未执行",
            )
            operation.result = {"error": operation.reason}
            operation.save(update_fields=["state", "reason", "result"])
        else:
            lease = secrets.token_urlsafe(32)
            operation.state, operation.lease_hash = "leased", digest(lease)
            operation.lease_until = timezone.now() + timedelta(seconds=30)
            operation.save(update_fields=["state", "lease_hash", "lease_until"])
            result["operation"] = {
                "id": str(operation.pk),
                "grant_id": str(operation.grant_id),
                "revision": operation.grant_revision,
                "tool": operation.tool,
                "arguments": operation.arguments,
                "lease": lease,
            }
    return result


def lock_operation(device, operation_id):
    original = LocalOperation.objects.get(pk=operation_id, grant__device=device)
    Task.objects.select_for_update().get(pk=original.attempt.task_id)
    attempt = Attempt.objects.select_for_update().get(pk=original.attempt_id)
    return attempt, LocalOperation.objects.select_for_update().select_related(
        "grant__device"
    ).get(pk=operation_id)


@transaction.atomic
def validate_lease(device, operation_id, lease):
    attempt, operation = lock_operation(device, operation_id)
    if (
        operation.state != "leased"
        or operation.lease_hash != digest(lease)
        or operation.lease_until < timezone.now()
        or not allowed(operation)
        or attempt.cancel_requested_at
        or attempt.state not in {"waiting_device", "waiting_approval"}
    ):
        raise ValueError("操作授权、任务或租约已失效，拒绝开始本地操作")


@transaction.atomic
def report(device, operation_id, lease, state, result):
    if state not in {"succeeded", "failed", "uncertain"}:
        raise ValueError("操作结果状态不合法")
    attempt, operation = lock_operation(device, operation_id)
    if not operation.lease_hash or operation.lease_hash != digest(lease):
        raise ValueError("操作领取凭证不匹配")
    if operation.state in TERMINAL:
        if operation.state != state or operation.result != result:
            raise ValueError("已保存的操作结果不可覆盖")
        return
    if (
        not allowed(operation)
        or attempt.cancel_requested_at
        or attempt.state not in {"waiting_device", "waiting_approval"}
    ):
        operation.state, operation.reason = (
            "uncertain",
            "授权或任务已撤销；迟到结果未采用，已开始的操作可能生效",
        )
    else:
        operation.state, operation.result = state, result
        operation.reason = str(result.get("error", ""))[:300]
    operation.save(update_fields=["state", "result", "reason"])
    from .workflow import maybe_resume_locked

    maybe_resume_locked(attempt)


def sweep():
    """结果不明确时只标记未知，不自动重新领取写入；失败结果可唤醒执行图。"""
    LocalOperation.objects.filter(
        state="leased", lease_until__lt=timezone.now()
    ).update(state="uncertain", reason="设备操作租约过期，结果待核实；不会自动重放")
    for operation in LocalOperation.objects.filter(state="pending").select_related(
        "grant__device"
    ):
        if not allowed(operation):
            LocalOperation.objects.filter(pk=operation.pk, state="pending").update(
                state="failed",
                reason="授权已撤销或改变，未执行本地操作",
                result={"error": "授权已撤销或改变"},
            )
    candidates = Attempt.objects.filter(
        state__in=["waiting_device", "waiting_approval"]
    ).values_list("pk", "task_id")
    for attempt_id, task_id in candidates:
        with transaction.atomic():
            Task.objects.select_for_update().get(pk=task_id)
            attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
            from .workflow import maybe_resume_locked

            maybe_resume_locked(attempt)
