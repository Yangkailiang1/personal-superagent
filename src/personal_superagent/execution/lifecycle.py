"""任务状态入口：先锁 Task 再锁 Attempt；状态与事件在同一事务提交。"""

from uuid import UUID
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404

from personal_superagent.tasks.models import Task
from personal_superagent.tasks.services import get_task
from .models import Attempt, RunEvent

ACTIVE = {"queued", "running", "waiting_approval", "waiting_device"}
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class StateConflict(ValueError):
    pass


def append_event(attempt: Attempt, kind: str, data: dict) -> None:
    """仅在持有 Attempt 行锁或新建事务内调用，保证单调序号。"""
    attempt.event_seq += 1
    attempt.save(update_fields=["event_seq"])
    RunEvent.objects.create(
        attempt=attempt, sequence=attempt.event_seq, kind=kind, data=data
    )


@transaction.atomic
def enqueue(
    *, user, task_id, request_key: UUID, mode: str, retry: bool = False
) -> Attempt:
    get_task(user=user, task_id=task_id)
    task = Task.objects.select_for_update().get(pk=task_id, owner=user)
    if task.kind != "task":
        raise StateConflict("接待调用只能从需求会话启动。")
    existing = task.attempts.filter(request_key=request_key).first()
    if existing:
        if existing.mode != mode:
            raise StateConflict("同一请求键不能切换执行模式。")
        return existing
    if task.execution_agent_id and task.execution_agent.executor_kind == "blender":
        from personal_superagent.modeling.services import enqueue as model_enqueue
        return model_enqueue(task,request_key,mode,retry)
    if task.release_id and task.dispatch.get("role")=="researcher" and mode=="real":
        from personal_superagent.modeling.research import enqueue as research_enqueue
        return research_enqueue(task,request_key,mode,retry)
    if task.execution_agent_id and task.execution_agent.executor_kind == "happier":
        from personal_superagent.happier.services import enqueue as external_enqueue
        return external_enqueue(task, request_key, mode, retry)
    if mode not in {"demo", "real"}:
        raise StateConflict("执行模式必须为 demo 或 real。")
    from django.conf import settings

    if mode == "real" and not settings.ALLOW_REAL_MODE:
        raise StateConflict("此部署只启用离线演示，真实模型尚未开放。")
    if mode == "real":
        from personal_superagent.model_status import status

        if status()["state"] != "ready":
            raise StateConflict("请先显式验证真实模型的工具调用能力。")
    if (
        task.attempts.filter(process_stopped=False).exists()
        or task.attempts.filter(state__in=ACTIVE).exists()
    ):
        raise StateConflict("任务仍有活动执行，或旧进程尚未确认停止。")
    if retry and task.status not in {"failed", "cancelled", "interrupted"}:
        raise StateConflict("仅失败、取消或中断任务可以重试。")
    if not retry and task.status != "pending":
        raise StateConflict("任务已经启动，请使用重试入口。")
    from personal_superagent.workflow import VERSION
    from personal_superagent.workflow.checkpoints import execution_config

    if task.release_id:
        from personal_superagent.workflow_v06 import VERSION
        from personal_superagent.workflow_v06.checkpoints import execution_config

        if not task.execution_agent_id:
            raise StateConflict("任务尚未路由")
    from personal_superagent.devices.workflow import scope_for

    scope = scope_for(task)
    if scope and task.release_id:
        scope["tools"] = [
            n for n in scope["tools"] if "local_" + n in task.dispatch["tools"]
        ]
    frozen = execution_config(mode)
    if task.release_id and task.execution_agent.device_id:
        frozen = task.execution_agent.model_config[mode]
    context = []
    if task.release_id:
        history = Task.objects.filter(
            owner=user,
            release__conversation=task.release.conversation,
            execution_agent=task.execution_agent,
            status="succeeded",
        ).order_by("-created_at")[:3]
        for old in history:
            if (
                old.release_id
                and old.release.conversation_id == task.release.conversation_id
            ):
                result = old.attempts.order_by("-created_at").first()
                context.append(
                    {
                        "task_id": str(old.pk),
                        "summary": result.result[:2000] if result else "",
                    }
                )
    if task.release_id:
        for dependency in task.dependencies.all():
            previous = dependency.attempts.order_by("-created_at").first()
            if previous:
                context.append(
                    {
                        "task_id": str(dependency.pk),
                        "summary": previous.result[:1500],
                        "documents": [
                            {"name": a.name, "content": a.content[:4000]}
                            for a in previous.artifacts.all()[:1]
                        ],
                    }
                )
    frozen_policy = dict(task.release.policy) if task.release_id else {}
    if task.release_id:
        routing_calls = sum(
            route.job.events.filter(kind="model").count()
            for route in task.routes.all()
            if route.job_id
        )
        frozen_policy["max_model_calls"] -= routing_calls
        if frozen_policy["max_model_calls"] <= 0:
            raise StateConflict("路由已用完模型额度，请调整 Plan 后重试")
    attempt = Attempt.objects.create(
        execution_device=task.execution_agent.device if task.release_id else None,
        task=task,
        request_key=request_key,
        mode=mode,
        input_snapshot={
            "title": task.title,
            "description": task.description + "\n相关职责上下文：" + str(context)
            if context
            else task.description,
            "workflow": frozen,
            "device": scope,
            "dispatch": task.dispatch,
            "policy": frozen_policy,
            "context": context,
        },
        workflow_version=VERSION,
        activity="等待 Worker 领取",
    )
    task.status = "queued"
    task.save(update_fields=["status"])
    append_event(attempt, "queued", {"mode": mode})
    return attempt


@transaction.atomic
def request_cancel(*, user, task_id, attempt_id) -> Attempt:
    get_task(user=user, task_id=task_id)
    task = Task.objects.select_for_update().get(pk=task_id, owner=user)
    attempt = get_object_or_404(
        Attempt.objects.select_for_update(), pk=attempt_id, task=task
    )
    if attempt.state not in ACTIVE or attempt.cancel_requested_at:
        return attempt
    attempt.cancel_requested_at = timezone.now()
    attempt.save(update_fields=["cancel_requested_at"])
    if attempt.state in {"queued", "waiting_approval", "waiting_device"} and attempt.process_stopped:
        attempt.approvals.filter(decision="pending").update(
            decision="cancelled", version=models.F("version") + 1
        )
        attempt.local_operations.filter(state="pending").update(
            state="failed",
            reason="任务已取消，操作未开始",
            result={"error": "任务已取消"},
        )
        attempt.local_operations.filter(state="leased").update(
            state="uncertain", reason="任务已取消；已开始的操作可能生效，回执待核实"
        )
        finish_locked(attempt, "cancelled", error="用户取消排队任务")
    else:
        append_event(attempt, "cancel_requested", {})
    return attempt


def finish_locked(
    attempt: Attempt, state: str, *, result: str = "", error: str = ""
) -> None:
    """调用方持有 Task/Attempt 锁；只在确认子进程停止后完成执行。"""
    attempt.state, attempt.result, attempt.error = state, result, error
    attempt.activity = dict(Task.Status.choices)[state]
    attempt.finished_at = (
        None if state in {"waiting_approval", "waiting_device"} else timezone.now()
    )
    attempt.save(update_fields=["state", "result", "error", "activity", "finished_at"])
    Task.objects.filter(pk=attempt.task_id).update(status=state)
    if attempt.input_snapshot.get("kind") == "intake":
        from personal_superagent.intake.services import project_result

        project_result(attempt)
    try:
        if attempt.input_snapshot.get("kind") == "routing":
            from personal_superagent.collaboration.routing import project_route

            project_route(attempt)
        if attempt.input_snapshot.get("kind") in {"knowledge", "inspection"}:
            from personal_superagent.knowledge.services import project

            project(attempt)
    except (ValueError, KeyError, TypeError):
        attempt.state = "failed"
        attempt.error = "管理 Agent 结果校验失败，未应用建议"
        attempt.activity = "结果无效"
        attempt.save(update_fields=["state", "error", "activity"])
        Task.objects.filter(pk=attempt.task_id).update(status="failed")
        from personal_superagent.collaboration.models import Proposal, RouteDecision

        Proposal.objects.filter(job=attempt).update(
            state="failed", report=attempt.error
        )
        RouteDecision.objects.filter(job=attempt).update(
            state="failed", reason=attempt.error
        )
    append_event(attempt, "finished", {"state": attempt.state, "error": attempt.error})


@transaction.atomic
def record_event(attempt_id, token, kind: str, data: dict) -> bool:
    task_id = Attempt.objects.values_list("task_id", flat=True).get(pk=attempt_id)
    Task.objects.select_for_update().get(pk=task_id)
    attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
    if (
        attempt.state != "running"
        or attempt.claim_token != token
        or attempt.cancel_requested_at
    ):
        return False
    if attempt.heartbeat_at < timezone.now() - timedelta(seconds=20):
        return False
    append_event(attempt, kind, data)
    from .projections import update_activity_locked

    update_activity_locked(attempt, kind, data)
    role = {
        "supervisor": "主助手",
        "writer": "内容整理",
        "reviewer": "质量检查",
        "intake": "需求接待",
    }.get(data.get("role"), "助手")
    activity = {
        "model": f"{role}正在处理",
        "plan": "计划已更新",
        "subagent_start": f"已委派：{role}",
        "subagent_end": f"{role}已返回",
        "tool_start": "正在调用工具：" + str(data.get("name", "")),
        "tool_end": "工具已返回：" + str(data.get("name", "")),
    }
    attempt.activity = activity.get(kind, attempt.activity)
    attempt.save(update_fields=["activity"])
    return True


@transaction.atomic
def complete(
    attempt_id,
    token,
    *,
    state: str,
    result: str = "",
    error: str = "",
    snapshot: dict | None = None,
) -> bool:
    task_id = Attempt.objects.values_list("task_id", flat=True).get(pk=attempt_id)
    Task.objects.select_for_update().get(pk=task_id)
    attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
    if attempt.claim_token != token:
        return False
    attempt.process_stopped = True
    attempt.save(update_fields=["process_stopped"])
    # 租约失效先入中断，迟到结果不可把它改成成功；只补充进程已停止事实。
    if attempt.state != "running":
        return False
    if attempt.heartbeat_at < timezone.now() - timedelta(seconds=20):
        finish_locked(
            attempt, "interrupted", error="结果返回时租约已失效；结果未采纳。"
        )
        return False
    if attempt.cancel_requested_at:
        state, result, error = "cancelled", "", "用户取消"
    elif snapshot:
        from .projections import apply_snapshot_locked

        apply_snapshot_locked(attempt, snapshot)
        if attempt.workflow_version == "0.6.0":
            from personal_superagent.collaboration.assets import project

            project(attempt, snapshot)
        if snapshot.get("pending"):
            state, result, error = "waiting_approval", "", ""
        elif snapshot.get("local_requests"):
            state, result, error = "waiting_device", "", ""
        elif snapshot.get("complete"):
            state, result, error = "succeeded", snapshot["result"], ""
        else:
            state, result, error = (
                "failed",
                "",
                "执行未返回最终回答或有效审批，不能标记成功。",
            )
    finish_locked(attempt, state, result=result, error=error)
    from personal_superagent.devices.workflow import maybe_resume_locked

    maybe_resume_locked(attempt)
    return True
