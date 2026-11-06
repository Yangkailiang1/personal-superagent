"""路由模型只建议；候选、历史优先和权限均由服务端确定。"""

from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from personal_superagent.tasks.models import Task
from personal_superagent.execution.models import Attempt
from .models import AgentProfile, RouteDecision
from .toolkit import capabilities

ROLES = {"writer", "reviewer", "researcher", "image_designer"}
BASIC = {"inspect_context", "add_numbers", "text_statistics"}


def role_tools(role):
    allowed = set(BASIC)
    if role == "researcher":
        if capabilities()["tavily_search"]:
            allowed.add("tavily_search")
        import json, os

        for server in json.loads(os.environ.get("MCP_CONFIG", "[]")):
            allowed |= {"mcp__" + n for n in server["allowed_tools"]}
    if role == "image_designer" and capabilities()["generate_image"]:
        allowed.add("generate_image")
    return allowed


def provision(user):
    from personal_superagent.model_status import status

    for role in ROLES:
        AgentProfile.objects.update_or_create(
            owner=user,
            identity_key="cloud:" + role,
            defaults={
                "name": "云端 " + role,
                "role": role,
                "tools": sorted(role_tools(role)),
                "modes": ["demo", "real"] if status()["state"] == "ready" else ["demo"],
            },
        )


def validate_step(user, step, policy):
    from personal_superagent.devices.models import Grant
    from personal_superagent.client.files import parts

    parts(step.source_path)
    if any(t.startswith("local_") for t in step.tools) and not step.grant_id:
        raise ValueError("本地文件任务必须明确授权目录")
    if step.grant_id:
        get_object_or_404(
            Grant,
            pk=step.grant_id,
            device__owner=user,
            device__revoked_at=None,
            revoked_at=None,
            local_enabled=True,
        )
    permitted = role_tools(step.role) | {
        "local_list_files",
        "local_read_text",
        "local_write_text",
    }
    if step.agent_id:
        chosen = get_object_or_404(
            AgentProfile, pk=step.agent_id, owner=user, enabled=True
        )
        permitted = set(chosen.tools)
    if not set(step.tools) <= permitted:
        raise ValueError("角色或工具尚不可用")
    if step.agent_id:
        agent = get_object_or_404(
            AgentProfile, pk=step.agent_id, owner=user, enabled=True
        )
        if not fits(agent, step.model_dump(), policy.model_dump(), online=False):
            raise ValueError("所选角色或授权不满足任务")
    elif not any(
        fits(a, step.model_dump(), policy.model_dump(), online=False)
        for a in AgentProfile.objects.filter(owner=user, enabled=True)
    ):
        raise ValueError("尚无满足工具和资源要求的 Agent")
    if "generate_image" in step.tools and policy.max_images < 1:
        raise ValueError("未授权生图额度")


def fits(agent, step, policy, online=True):
    if (
        agent.role != step["role"]
        or not set(step["tools"]) <= set(agent.tools)
        or policy["mode"] not in agent.modes
    ):
        return False
    if step.get("grant_id") and str(agent.grant_id) != step["grant_id"]:
        return False
    if agent.device_id:
        if agent.device.revoked_at or (
            agent.grant and (agent.grant.revoked_at or not agent.grant.local_enabled)
        ):
            return False
        if online and (
            not agent.last_seen
            or agent.last_seen < timezone.now() - timedelta(seconds=20)
        ):
            return False
    return True


def candidates(task):
    step = task.dispatch
    policy = task.release.policy
    items = [
        a
        for a in AgentProfile.objects.filter(
            owner=task.owner, enabled=True
        ).select_related("device", "grant")
        if fits(a, step, policy)
    ]
    if step.get("agent_id"):
        items = [a for a in items if str(a.pk) == step["agent_id"]]
    if not items:
        return []
    # 只在同一会话任务线继承职责，不串入整个用户历史。
    previous = (
        Task.objects.filter(
            owner=task.owner,
            release__conversation=task.release.conversation,
            status="succeeded",
            dispatch__role=step["role"],
            execution_agent__in=items,
        )
        .order_by("-created_at")
        .first()
    )
    if previous:
        items = [a for a in items if a.pk == previous.execution_agent_id]
    occupied = set(
        Attempt.objects.filter(process_stopped=False).values_list(
            "task__execution_agent_id", flat=True
        )
    )
    available = [a for a in items if a.pk not in occupied]
    return available or []


@transaction.atomic
def dispatch_pending():
    from .jobs import enqueue_job

    for task in (
        Task.objects.select_for_update(skip_locked=True)
        .filter(release__active=True, status="pending")
        .select_related("release", "owner")
    ):
        if task.dependencies.exclude(status="succeeded").exists():
            continue
        if task.routes.filter(state="queued").exists():
            continue
        if task.routes.filter(state="failed").exists():
            continue  # 失败需用户显式处理，不自动无限重试
        if task.execution_agent_id:
            if not fits(task.execution_agent, task.dispatch, task.release.policy):
                continue
            try:
                start_assigned(task)
            except ValueError:
                RouteDecision.objects.create(
                    task=task,
                    state="failed",
                    reason="执行配置、授权或额度已改变，请调整计划",
                )
            continue
        options = candidates(task)
        if not options:
            continue
        snapshot = {
            "max_calls": min(8, task.release.policy["max_model_calls"]),
            "task_id": str(task.pk),
            "goal": task.description,
            "candidates": [
                {
                    "id": str(a.pk),
                    "name": a.name,
                    "role": a.role,
                    "device": str(a.device_id) if a.device_id else None,
                }
                for a in options
            ],
        }
        try:
            job = enqueue_job(
                task.owner, "routing", snapshot, task.release.policy["mode"]
            )
        except ValueError:
            RouteDecision.objects.create(
                task=task, state="failed", reason="路由模型配置未就绪，未发送请求"
            )
            continue
        RouteDecision.objects.create(
            task=task, job=job, candidates=[str(a.pk) for a in options]
        )


def start_assigned(task):
    from personal_superagent.execution.lifecycle import enqueue
    import uuid

    enqueue(
        user=task.owner,
        task_id=task.pk,
        request_key=uuid.uuid4(),
        mode=task.release.policy["mode"],
    )


def project_route(attempt):
    import json

    route = RouteDecision.objects.select_for_update().get(job=attempt)
    if attempt.state != "succeeded":
        route.state = "failed"
        route.reason = attempt.error
        route.save()
        return
    result = json.loads(attempt.result)
    selected = result.get("agent_id")
    task = Task.objects.select_for_update().get(pk=route.task_id)
    eligible = {str(a.pk): a for a in candidates(task)}
    if selected not in route.candidates or selected not in eligible:
        route.state = "failed"
        route.reason = "候选已失效或路由结果越权，未派工"
    else:
        task.execution_agent = eligible[selected]
        task.save(update_fields=["execution_agent"])
        route.agent = eligible[selected]
        route.reason = result.get("reason", "")
        route.state = "selected"
    route.save()
