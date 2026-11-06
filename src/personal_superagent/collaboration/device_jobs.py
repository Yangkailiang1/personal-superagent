"""设备执行控制面：不使用服务器 PID 推断本机进程，晚返回不得复活终态。"""

import hashlib
import json
import uuid
from django.db import transaction
from django.utils import timezone
from personal_superagent.devices.models import Device, Grant
from personal_superagent.execution.claims import claim_next, heartbeat
from personal_superagent.execution.models import Attempt
from personal_superagent.execution.lifecycle import complete, record_event, append_event
from personal_superagent.tasks.models import Task
from .models import AgentProfile, DeviceReceipt
from .routing import ROLES, BASIC, fits
from .permissions import check_scope


def hello(device, data):
    profiles = data.get("profiles", [])
    if not isinstance(profiles, list) or len(profiles) > 68:
        raise ValueError("能力清单过长")
    with transaction.atomic():
        device = Device.objects.select_for_update().get(pk=device.pk, revoked_at=None)
        device.last_seen = timezone.now()
        device.save(update_fields=["last_seen"])
        from personal_superagent.devices.protocol import sync_grants

        sync_grants(
            device,
            data.get(
                "grants",
                [
                    {"id": str(g.pk), "label": g.label, "tools": g.tools}
                    for g in device.grants.filter(local_enabled=True)
                ],
            ),
        )
        seen = []
        for p in profiles:
            if p["role"] not in ROLES or not set(p["modes"]) <= {"demo", "real"}:
                raise ValueError("角色或模式无效")
            if (
                p.get("grant_id")
                and Grant.objects.filter(pk=p["grant_id"], device=device)
                .exclude(revoked_at=None)
                .exists()
            ):
                continue
            grant = (
                Grant.objects.get(
                    pk=p["grant_id"], device=device, revoked_at=None, local_enabled=True
                )
                if p.get("grant_id")
                else None
            )
            allowed = (
                set(BASIC)
                | {"tavily_search", "generate_image"}
                | {"local_" + n for n in grant.tools}
                if grant
                else set(BASIC) | {"tavily_search", "generate_image"}
            )
            tools = p["tools"]
            if not isinstance(tools, list) or any(
                not isinstance(t, str)
                or (t not in allowed and not t.startswith("mcp__"))
                for t in tools
            ):
                raise ValueError("工具声明无效")
            if p["role"] != "researcher" and any(
                t == "tavily_search" or t.startswith("mcp__") for t in tools
            ):
                raise ValueError("角色不允许搜索")
            if p["role"] != "image_designer" and "generate_image" in tools:
                raise ValueError("角色不允许生图")
            cfg = p["model_config"]
            for mode in p["modes"]:
                if (
                    set(cfg[mode]) != {"version", "code_hash", "model", "endpoint_hash"}
                    or cfg[mode]["version"] != "0.6.0"
                ):
                    raise ValueError("执行版本无效")
            key = f"device:{device.pk}:{p['role']}:{grant.pk if grant else 'cloud'}"
            agent, _ = AgentProfile.objects.update_or_create(
                owner=device.owner,
                identity_key=key,
                defaults={
                    "device": device,
                    "grant": grant,
                    "name": device.name + " / " + p["role"],
                    "role": p["role"],
                    "tools": tools,
                    "modes": p["modes"],
                    "model_config": cfg,
                    "last_seen": timezone.now(),
                    "enabled": True,
                },
            )
            seen.append(agent.pk)
        AgentProfile.objects.filter(device=device).exclude(pk__in=seen).update(
            enabled=False
        )
    return {"profiles": len(seen)}


def claim(device):
    attempt = claim_next(uuid.uuid4(), device)
    if not attempt:
        return {"job": None}
    agent = attempt.task.execution_agent
    if (
        not agent
        or not agent.enabled
        or not check_scope(attempt, agent)
        or not fits(agent, attempt.task.dispatch, attempt.task.release.policy)
    ):
        complete(
            attempt.pk,
            attempt.claim_token,
            state="failed",
            error="设备资源或授权已改变",
        )
        return {"job": None}
    decisions = {}
    for approval in attempt.approvals.filter(
        checkpoint_id=attempt.checkpoint_id
    ).order_by("interrupt_id", "action_index"):
        if approval.decision in {"approve", "reject"}:
            decisions.setdefault(approval.interrupt_id, {"decisions": []})[
                "decisions"
            ].append({"type": approval.decision})
    return {
        "job": {
            "id": str(attempt.pk),
            "token": str(attempt.claim_token),
            "workflow_version": attempt.workflow_version,
            "mode": attempt.mode,
            "snapshot": attempt.input_snapshot,
            "action": attempt.execution_action,
            "decisions": decisions,
        }
    }


@transaction.atomic
def control(device, data):
    attempt = Attempt.objects.get(
        pk=data["id"], execution_device=device, task__owner=device.owner
    )
    Task.objects.select_for_update().get(pk=attempt.task_id)
    attempt = Attempt.objects.select_for_update().get(pk=attempt.pk)
    token = uuid.UUID(data["token"])
    if token != attempt.claim_token:
        raise ValueError("领取凭证无效")
    action = data["action"]
    if action == "heartbeat":
        if "grants" in data:
            from personal_superagent.devices.protocol import sync_grants

            sync_grants(device, data["grants"])
        AgentProfile.objects.filter(device=device).update(last_seen=timezone.now())
        Device.objects.filter(pk=device.pk).update(last_seen=timezone.now())
        if (
            device.revoked_at
            or not attempt.task.execution_agent.enabled
            or not check_scope(attempt, attempt.task.execution_agent)
            or not fits(
                attempt.task.execution_agent,
                attempt.task.dispatch,
                attempt.task.release.policy,
                online=False,
            )
        ):
            return {"continue": False}
        return {
            "continue": not attempt.cancel_requested_at and heartbeat(attempt.pk, token)
        }
    if action == "image":
        if (attempt.state != "running" or attempt.cancel_requested_at) and not (
            __import__(
                "personal_superagent.collaboration.assets", fromlist=["directory"]
            ).directory(attempt)
            / data["name"]
        ).is_file():
            raise ValueError("执行已停止")
        from .assets import upload

        upload(attempt, data["name"], data["content"])
        return {"ok": True}
    if action == "event":
        if data["kind"] not in {
            "model",
            "plan",
            "tool_start",
            "tool_end",
            "subagent_start",
            "subagent_end",
            "subgraph",
        }:
            raise ValueError("事件类型无效")
        # 同一领取凭证下按序号去重。设备发送日志为展示证据，不是系统独立验证。
        sequence = int(data["sequence"])
        cursor_key = hashlib.sha256(str(token).encode()).hexdigest()
        last = (
            attempt.events.filter(kind="device_cursor", data__lease_digest=cursor_key)
            .order_by("-sequence")
            .first()
        )
        previous = last.data["cursor"] if last else 0
        if sequence <= previous:
            return {"ok": True}
        if sequence != previous + 1:
            raise ValueError("事件游标不连续")
        if record_event(attempt.pk, token, data["kind"], data["data"]):
            attempt.refresh_from_db(fields=["event_seq"])
            append_event(
                attempt,
                "device_cursor",
                {"cursor": sequence, "lease_digest": cursor_key},
            )
        return {"ok": True}
    if action == "result":
        result = data["result"]
        digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        receipt = DeviceReceipt.objects.filter(attempt=attempt, token=token).first()
        if receipt:
            if receipt.digest != digest:
                raise ValueError("重复结果不能覆盖")
            return {"ok": True}
        if result.get("state") not in {
            "succeeded",
            "failed",
            "interrupted",
            "cancelled",
        }:
            raise ValueError("终态无效")
        # 只在当前运行态接受快照，取消/租约失效后仅确认设备已停止。
        snap = result.get("snapshot")
        if snap and attempt.state == "running" and not attempt.cancel_requested_at:
            if not isinstance(snap, dict) or not snap.get("checkpoint_id"):
                raise ValueError("快照无效")
        DeviceReceipt.objects.create(attempt=attempt, token=token, digest=digest)
        complete(
            attempt.pk,
            token,
            state=result["state"],
            error=result.get("error", "")[:1000],
            snapshot=snap,
        )
        return {"ok": True}
    raise ValueError("动作无效")
