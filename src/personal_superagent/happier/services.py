"""HappierExecutor 业务桥：所有状态与事件短事务提交，不持锁等待本机。"""

import hashlib
import json
import uuid
from datetime import timedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from personal_superagent.collaboration.models import AgentProfile
from personal_superagent.devices.models import Device
from personal_superagent.tasks.models import Task
from personal_superagent.execution.models import Attempt
from personal_superagent.execution.claims import claim_next
from personal_superagent.execution.lifecycle import (
    ACTIVE,
    StateConflict,
    append_event,
    finish_locked,
    complete,
)
from .models import Repository, ExternalRun, Permission
from .policy import RepositoryPolicy, Delivery, validate_manifest, subset

TOOLS = ["repository_read", "repository_write", "repository_command"]


@transaction.atomic
def hello(device, data):
    Device.objects.select_for_update().get(pk=device.pk, revoked_at=None)
    repos = data["repositories"]
    if not isinstance(repos, list) or len(repos) > 16:
        raise ValueError("仓库数量无效")
    seen = []
    for item in repos:
        policy = validate_manifest(item)
        old = Repository.objects.filter(pk=item["id"]).first()
        if old and old.device_id != device.pk:
            raise ValueError("仓库不属于当前设备")
        agent, _ = AgentProfile.objects.update_or_create(
            owner=device.owner,
            identity_key=f"happier:{device.pk}:{item['id']}",
            defaults={
                "name": device.name + " / Claude / " + item["label"],
                "role": "coder",
                "device": device,
                "tools": TOOLS,
                "modes": ["real"] if data.get("ready") is True else [],
                "executor_kind": "happier",
                "enabled": data.get("ready") is True,
                "last_seen": timezone.now(),
            },
        )
        changed = old and (
            old.baseline != item["baseline"] or old.policy != policy or not old.enabled
        )
        Repository.objects.update_or_create(
            pk=item["id"],
            defaults={
                "device": device,
                "agent": agent,
                "label": item["label"],
                "baseline": item["baseline"],
                "policy": policy,
                "enabled": True,
                "version": old.version + bool(changed) if old else 1,
            },
        )
        seen.append(item["id"])
    Repository.objects.filter(device=device).exclude(pk__in=seen).update(enabled=False)
    AgentProfile.objects.filter(device=device, executor_kind="happier").exclude(
        repository__id__in=seen
    ).update(enabled=False)
    Device.objects.filter(pk=device.pk).update(last_seen=timezone.now())
    return {"repositories": len(seen)}


def eligible(agent, step):
    if agent.executor_kind == "blender":
        from personal_superagent.modeling.services import eligible as model_eligible
        return model_eligible(agent, step)
    repo = Repository.objects.filter(
        agent=agent, enabled=True, device__revoked_at=None
    ).first()
    return bool(
        repo
        and str(repo.pk) == step.get("repository_id")
        and repo.version == step.get("repository_version")
        and repo.baseline == step.get("base_commit")
        and subset(step.get("write_paths", []), repo.policy["write_paths"])
        and set(step.get("checks", [])) <= set(repo.policy["checks"])
    )


def enqueue(task, key, mode, retry):
    """调用方已锁 Task；本机模型不依赖云端 OpenAI Key，也不伪装演示执行。"""
    if (
        mode != "real"
        or mode not in task.execution_agent.modes
        or not task.execution_agent.enabled
    ):
        raise StateConflict("HappierExecutor 需要本机 Claude 就绪，仅支持真实执行")
    if (
        task.attempts.filter(process_stopped=False).exists()
        or task.attempts.filter(state__in=ACTIVE).exists()
    ):
        raise StateConflict("已有活动执行或旧进程尚未确认停止")
    if (retry and task.status not in {"failed", "cancelled", "interrupted"}) or (
        not retry and task.status != "pending"
    ):
        raise StateConflict("任务状态不允许启动")
    if task.dependencies.exclude(status="succeeded").exists() or not eligible(
        task.execution_agent, task.dispatch
    ):
        raise StateConflict("依赖、代码基线或仓库授权已改变，请重新确认计划")
    repo = task.execution_agent.repository
    policy = RepositoryPolicy.model_validate(
        {
            **repo.policy,
            "write_paths": task.dispatch["write_paths"],
            "checks": task.dispatch["checks"],
            "timeout": min(repo.policy["timeout"], task.release.policy["timeout"]),
        }
    ).model_dump()
    context = [
        {
            "task_id": str(t.pk),
            "result": t.attempts.order_by("-created_at").first().result[:3000],
        }
        for t in task.dependencies.all()
    ]
    for previous in Task.objects.filter(
        owner=task.owner,
        release__conversation=task.release.conversation,
        execution_agent=task.execution_agent,
        status="succeeded",
    ).order_by("-created_at")[:3]:
        if all(item["task_id"] != str(previous.pk) for item in context):
            context.append(
                {
                    "task_id": str(previous.pk),
                    "result": previous.attempts.order_by("-created_at")
                    .first()
                    .result[:2000],
                }
            )
    attempt = Attempt.objects.create(
        task=task,
        request_key=key,
        mode="real",
        executor_kind="happier",
        execution_device=repo.device,
        workflow_version="happier-0.7",
        input_snapshot={
            "title": task.title,
            "description": task.description,
            "executor": "happier",
            "repository_id": str(repo.pk),
            "repository_version": repo.version,
            "base_commit": repo.baseline,
            "policy": policy,
            "dispatch": task.dispatch,
            "context": context,
        },
        activity="等待本机 Claude 执行器",
    )
    ExternalRun.objects.create(attempt=attempt)
    task.status = "queued"
    task.save(update_fields=["status"])
    append_event(
        attempt, "queued", {"executor": "happier", "device": str(repo.device_id)}
    )
    return attempt


def claim(device):
    attempt = claim_next(uuid.uuid4(), device, executor_kind="happier")
    if not attempt:
        return {"job": None}
    if not eligible(attempt.task.execution_agent, attempt.input_snapshot["dispatch"]):
        complete(
            attempt.pk, attempt.claim_token, state="failed", error="仓库授权已改变"
        )
        return {"job": None}
    return {
        "job": {
            "id": str(attempt.pk),
            "task_id": str(attempt.task_id),
            "token": str(attempt.claim_token),
            "instance": str(attempt.external_run.instance),
            "snapshot": attempt.input_snapshot,
        }
    }


@transaction.atomic
def control(device, data):
    original = get_object_or_404(
        Attempt,
        pk=data["id"],
        execution_device=device,
        task__owner=device.owner,
        executor_kind__in=["happier", "blender"],
    )
    Task.objects.select_for_update().get(pk=original.task_id)
    a = Attempt.objects.select_for_update().get(pk=original.pk)
    run = ExternalRun.objects.select_for_update().get(
        attempt=a, instance=data["instance"]
    )
    if str(a.claim_token) != data["token"]:
        raise StateConflict("领取凭证已失效")
    action = data["action"]
    alive = (
        a.state in {"running", "waiting_approval"}
        and not a.cancel_requested_at
        and a.heartbeat_at >= timezone.now() - timedelta(seconds=20)
    )
    if action == "heartbeat":
        valid = (
            alive
            and eligible(a.task.execution_agent, a.input_snapshot["dispatch"])
            and a.task.execution_agent.enabled
        )
        if valid:
            a.heartbeat_at = timezone.now()
            a.save(update_fields=["heartbeat_at"])
            AgentProfile.objects.filter(pk=a.task.execution_agent_id).update(
                last_seen=timezone.now()
            )
            Device.objects.filter(pk=device.pk).update(last_seen=timezone.now())
        return {
            "continue": bool(valid),
            "decisions": list(
                run.permissions.filter(
                    decision__in=["approve", "reject"], applied=False
                ).values("request_id", "decision", "version")
            ),
        }
    if action == "result":
        report = Delivery.model_validate(data["report"]).model_dump()
        report["independent_verification"] = False
        if a.executor_kind == "blender" and (report["files"] or report["diff"]):
            raise ValueError("建模文件内容不能上传云端")
        canonical = dict(report)
        if "local_files" not in data["report"]:
            canonical.pop("local_files", None)
        digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode()
        ).hexdigest()
        if run.receipt_digest:
            if run.receipt_digest != digest:
                raise StateConflict("重复结果不能覆盖")
            return {"ok": True}
        if report["state"] not in {"succeeded", "failed", "interrupted", "cancelled"}:
            raise ValueError("终态无效")
        if alive:
            if (
                a.state == "waiting_approval"
                and run.permissions.filter(applied=False).exists()
            ):
                raise StateConflict("审批未确认，不能完成")
            a.state = "running"
            a.save(update_fields=["state"])
            # 真实字节差异与检查证据来自本机，不冒充独立验证。
            state = report["state"]
            if (
                report.get("violations")
                or any(c.get("exit_code") != 0 for c in report.get("checks", []))
                or [c["command"] for c in report["checks"]]
                != a.input_snapshot["policy"]["checks"]
                or not subset(
                    report["changed_paths"], a.input_snapshot["policy"]["write_paths"]
                )
            ):
                state = "failed"
            complete(
                a.pk,
                a.claim_token,
                state=state,
                error=report.get("error", "")
                or ("执行或交付检查未通过" if state == "failed" else ""),
            )
            a.refresh_from_db()
            if a.state == "succeeded":
                a.result = report.get("text", "")
                a.save(update_fields=["result"])
        else:
            # 迟到结果只能确认旧进程停止，不能复活终态。
            if a.state in {"running", "waiting_approval"}:
                finish_locked(
                    a,
                    "cancelled" if a.cancel_requested_at else "interrupted",
                    error="执行已取消或租约失效",
                )
            a.process_stopped = True
            a.save(update_fields=["process_stopped"])
        from personal_superagent.modeling.services import track
        track(a, report["local_files"])
        run.report = report
        run.receipt_digest = digest
        run.save(update_fields=["report", "receipt_digest"])
        run.permissions.filter(applied=False).update(decision="cancelled")
        append_event(
            a,
            "external_collected",
            {"state": a.state, "independent_verification": False},
        )
        return {"ok": True}
    if not alive:
        raise StateConflict("执行已停止或租约失效")
    if action != "event":
        raise ValueError("动作无效")
    seq = int(data["sequence"])
    event = data["event"]
    if seq <= run.cursor:
        old = a.events.filter(data__external_sequence=seq).first()
        if not old or old.data != {**event, "external_sequence": seq}:
            raise StateConflict("重复事件内容发生变化")
        return {"ok": True}
    if seq != run.cursor + 1:
        raise StateConflict("事件游标不连续")
    kind = event["kind"]
    if kind not in {
        "session",
        "text",
        "tool_start",
        "tool_end",
        "permission",
        "permission_applied",
        "check",
        "activity",
    }:
        raise ValueError("事件类型无效")
    if kind == "session":
        run.session_id = str(event["session_id"])[:160]
        if a.executor_kind == "blender":
            a.activity = "本机模型正在设计场景"
    if kind == "permission":
        p, created = Permission.objects.get_or_create(
            run=run,
            request_id=event["request_id"],
            defaults={"tool": event["tool"], "arguments": event["args"]},
        )
        if not created and (p.tool != event["tool"] or p.arguments != event["args"]):
            raise StateConflict("审批 ID 内容发生变化")
        a.state = "waiting_approval"
        a.activity = "等待 Claude 工具审批（保留执行额度）"
        Task.objects.filter(pk=a.task_id).update(status="waiting_approval")
    elif kind == "permission_applied":
        p = run.permissions.get(request_id=event["request_id"])
        if p.decision != event["decision"] or p.decision not in {"approve", "reject"}:
            raise StateConflict("审批决定不匹配")
        p.applied = True
        p.save(update_fields=["applied"])
        if not run.permissions.filter(applied=False).exists():
            a.state = "running"
            a.activity = "Claude 继续执行"
            Task.objects.filter(pk=a.task_id).update(status="running")
    elif kind in {"tool_start", "activity"}:
        a.activity = (
            "Claude：" + str(event.get("tool", event.get("text", "执行中")))[:100]
        )
        if a.executor_kind == "blender":
            a.activity = {
                "mcp__blender__build_model": "Blender 正在构建几何与材质",
                "mcp__blender__inspect_model": "Blender 正在检查场景",
                "mcp__blender__render_model": "Blender 正在渲染预览",
            }.get(event.get("tool"), str(event.get("text", "本机模型正在处理"))[:100])
    a.save(update_fields=["state", "activity"])
    append_event(a, "external_" + kind, {**event, "external_sequence": seq})
    run.cursor = seq
    run.save(update_fields=["cursor", "session_id"])
    return {"ok": True}


@transaction.atomic
def decide(user, data):
    original = get_object_or_404(
        Permission, pk=data["id"], run__attempt__task__owner=user
    )
    Task.objects.select_for_update().get(pk=original.run.attempt.task_id)
    a = Attempt.objects.select_for_update().get(pk=original.run.attempt_id)
    p = Permission.objects.select_for_update().get(pk=original.pk)
    key = uuid.UUID(data["request_key"])
    if p.request_key == key and p.decision == data["decision"]:
        return p
    if (
        a.state != "waiting_approval"
        or a.cancel_requested_at
        or a.heartbeat_at < timezone.now() - timedelta(seconds=20)
    ):
        raise StateConflict("执行已停止或设备失联")
    if (
        p.version != data["version"]
        or p.decision != "pending"
        or data["decision"] not in {"approve", "reject"}
    ):
        raise StateConflict("审批已更新，请刷新")
    p.decision = data["decision"]
    p.version += 1
    p.request_key = key
    p.save()
    append_event(
        a, "external_decision", {"permission_id": p.pk, "decision": p.decision}
    )
    return p


def snapshot(attempt):
    if attempt.executor_kind not in {"happier", "blender"}:
        return None
    run = attempt.external_run
    return {
        "instance": str(run.instance),
        "session_id": run.session_id,
        "repository_id": attempt.input_snapshot.get("repository_id"),
        "baseline": attempt.input_snapshot.get("base_commit", ""),
        "policy": attempt.input_snapshot["policy"],
        "report": run.report,
        "can_decide": bool(
            attempt.state == "waiting_approval"
            and not attempt.cancel_requested_at
            and attempt.heartbeat_at
            and attempt.heartbeat_at >= timezone.now() - timedelta(seconds=20)
        ),
        "permissions": list(
            run.permissions.values(
                "id", "tool", "arguments", "version", "decision", "applied"
            )
        ),
    }
