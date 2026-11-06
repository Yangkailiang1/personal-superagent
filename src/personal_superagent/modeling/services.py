"""模型建议能力，服务器验证设备归属和授权；离线时不替换执行地点。"""

import uuid
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from personal_superagent.collaboration.models import AgentProfile
from personal_superagent.execution.models import Attempt
from personal_superagent.execution.lifecycle import StateConflict, append_event, ACTIVE
from personal_superagent.happier.models import ExternalRun
from personal_superagent.execution.claims import claim_next
from personal_superagent.devices.models import Device
from .models import Capability, LocalFile

TOOLS = ["blender_modeling"]


@transaction.atomic
def hello(device, data):
    Device.objects.select_for_update().get(pk=device.pk, revoked_at=None)
    config = data["config"]
    if (
        set(config)
        != {"provider_fingerprint", "model", "addon_hash", "protocol", "grant_id"}
        or config["protocol"] != 15
        or len(config["provider_fingerprint"]) != 64
        or len(config["addon_hash"]) != 64
    ):
        raise ValueError("设备能力配置无效")
    grant = uuid.UUID(config["grant_id"])
    agent, _ = AgentProfile.objects.update_or_create(
        owner=device.owner,
        identity_key="blender:" + str(device.pk),
        defaults={
            "name": device.name + " / Blender 建模",
            "role": "modeler",
            "device": device,
            "executor_kind": "blender",
            "tools": TOOLS,
            "modes": ["real"],
            "enabled": True,
            "last_seen": timezone.now(),
        },
    )
    Capability.objects.update_or_create(
        device=device,
        defaults={"agent": agent, "grant_id": grant, "config": config, "enabled": True},
    )
    Device.objects.filter(pk=device.pk).update(last_seen=timezone.now())
    return {"agent_id": str(agent.pk)}


def eligible(agent, step):
    cap = Capability.objects.filter(
        agent=agent, enabled=True, device__revoked_at=None
    ).first()
    return bool(
        cap
        and set(step.get("required_capabilities", [])) == {"blender.modeling"}
        and set(step.get("tools", [])) <= set(TOOLS)
    )


def enqueue(task, key, mode, retry):
    if (
        mode != "real"
        or not task.release_id
        or not eligible(task.execution_agent, task.dispatch)
    ):
        raise StateConflict("建模需要已发布真实计划和有效设备能力")
    if (
        task.attempts.filter(state__in=ACTIVE).exists()
        or task.attempts.filter(process_stopped=False).exists()
    ):
        raise StateConflict("仍有活动执行或未确认停止")
    if (retry and task.status not in {"failed", "cancelled", "interrupted"}) or (
        not retry and task.status != "pending"
    ):
        raise StateConflict("任务状态不允许启动")
    if task.dependencies.exclude(status="succeeded").exists():
        raise StateConflict("研究依赖未完成")
    cap = task.execution_agent.capability
    context = [
        {
            "task_id": str(t.pk),
            "result": t.attempts.order_by("-created_at").first().result[:16000],
        }
        for t in task.dependencies.all()
    ]
    a = Attempt.objects.create(
        task=task,
        request_key=key,
        mode="real",
        executor_kind="blender",
        execution_device=cap.device,
        workflow_version="blender-0.8",
        input_snapshot={
            "title": task.title,
            "description": task.description,
            "dispatch": task.dispatch,
            "context": context,
            "capability": cap.config,
            "policy": {
                "max_turns": 16,
                "timeout": min(1800, task.release.policy["timeout"]),
                "checks": [],
                "write_paths": [],
            },
        },
        activity="等待具备 Blender 能力的本机 Agent",
    )
    ExternalRun.objects.create(attempt=a)
    task.status = "queued"
    task.save(update_fields=["status"])
    append_event(a, "queued", {"executor": "blender", "capability": "blender.modeling"})
    return a


def claim(device):
    a = claim_next(uuid.uuid4(), device, executor_kind="blender")
    if not a:
        return {"job": None}
    return {
        "job": {
            "id": str(a.pk),
            "task_id": str(a.task_id),
            "token": str(a.claim_token),
            "instance": str(a.external_run.instance),
            "snapshot": a.input_snapshot,
        }
    }


def track(a, files):
    from pathlib import PurePosixPath
    import re

    if a.executor_kind != "blender" or a.state != "succeeded":
        return
    if not {"model.blend", "preview.png"} <= set(f["path"] for f in files):
        raise ValueError("缺少建模交付")
    for f in files:
        p = PurePosixPath(f["path"])
        if (
            p.is_absolute()
            or ".." in p.parts
            or len(p.parts) != 1
            or not re.fullmatch(r"[a-zA-Z0-9_.-]+", str(p))
            or not re.fullmatch("[0-9a-f]{64}", f["sha256"])
        ):
            raise ValueError("文件追踪记录无效")
        if f["size"] <= 0 or f["size"] > 100 * 1024 * 1024:
            raise ValueError("文件大小无效")
        LocalFile.objects.get_or_create(
            attempt=a,
            path=f["path"],
            defaults={
                "device": a.execution_device,
                "grant_id": a.input_snapshot["capability"]["grant_id"],
                "media_type": f["media_type"],
                "sha256": f["sha256"],
                "size": f["size"],
            },
        )


def files_for(a):
    online = bool(
        a.execution_device
        and not a.execution_device.revoked_at
        and a.execution_device.last_seen
        and a.execution_device.last_seen >= timezone.now() - timedelta(seconds=20)
    )
    return [
        {**f, "device_online": online, "device_name": a.execution_device.name}
        for f in a.local_files.values(
            "id", "path", "media_type", "size", "sha256", "state", "checked_at"
        )
    ]


@transaction.atomic
def file_poll(device, data):
    items = data.get("files", [])
    if len(items) > 200:
        raise ValueError("追踪记录过多")
    Device.objects.filter(pk=device.pk).update(last_seen=timezone.now())
    AgentProfile.objects.filter(device=device, executor_kind="blender").update(
        last_seen=timezone.now()
    )
    for f in items:
        if f["state"] not in {"available", "changed", "missing"}:
            raise ValueError("文件状态无效")
        LocalFile.objects.filter(
            pk=f["id"], device=device, attempt__task__owner=device.owner
        ).update(state=f["state"], checked_at=timezone.now())
    selected = list(
        LocalFile.objects.filter(device=device, open_requested=True).values(
            "id", "attempt_id", "path", "sha256", "open_request_id"
        )
    )
    # 交互命令确认后才移除，重传由本机打开账本去重。
    for id in data.get("opened", []):
        LocalFile.objects.filter(open_request_id=id, device=device).update(
            open_requested=False
        )
    return {
        "files": list(
            LocalFile.objects.filter(device=device).values(
                "id", "attempt_id", "path", "sha256"
            )
        ),
        "open": selected,
    }
