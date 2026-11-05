"""任务状态入口：先锁 Task 再锁 Attempt；状态与事件在同一事务提交。"""
from uuid import UUID
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404

from personal_superagent.tasks.models import Task
from personal_superagent.tasks.services import get_task
from .models import Attempt, RunEvent

ACTIVE = {"queued", "running"}
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class StateConflict(ValueError):
    pass


def append_event(attempt: Attempt, kind: str, data: dict) -> None:
    """仅在持有 Attempt 行锁或新建事务内调用，保证单调序号。"""
    attempt.event_seq += 1
    attempt.save(update_fields=["event_seq"])
    RunEvent.objects.create(attempt=attempt, sequence=attempt.event_seq, kind=kind, data=data)


@transaction.atomic
def enqueue(*, user, task_id, request_key: UUID, mode: str, retry: bool = False) -> Attempt:
    get_task(user=user, task_id=task_id)
    task = Task.objects.select_for_update().get(pk=task_id, owner=user)
    existing = task.attempts.filter(request_key=request_key).first()
    if existing:
        if existing.mode != mode:
            raise StateConflict("同一请求键不能切换执行模式。")
        return existing
    if mode not in {"demo", "real"}:
        raise StateConflict("执行模式必须为 demo 或 real。")
    if task.attempts.filter(process_stopped=False).exists() or task.attempts.filter(state__in=ACTIVE).exists():
        raise StateConflict("任务仍有活动执行，或旧进程尚未确认停止。")
    if retry and task.status not in {"failed", "cancelled", "interrupted"}:
        raise StateConflict("仅失败、取消或中断任务可以重试。")
    if not retry and task.status != "pending":
        raise StateConflict("任务已经启动，请使用重试入口。")
    attempt = Attempt.objects.create(
        task=task, request_key=request_key, mode=mode,
        input_snapshot={"title": task.title, "description": task.description},
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
    attempt = get_object_or_404(Attempt.objects.select_for_update(), pk=attempt_id, task=task)
    if attempt.state not in ACTIVE or attempt.cancel_requested_at:
        return attempt
    attempt.cancel_requested_at = timezone.now()
    attempt.save(update_fields=["cancel_requested_at"])
    if attempt.state == "queued":
        finish_locked(attempt, "cancelled", error="用户取消排队任务")
    else:
        append_event(attempt, "cancel_requested", {})
    return attempt


def finish_locked(attempt: Attempt, state: str, *, result: str = "", error: str = "") -> None:
    """调用方持有 Task/Attempt 锁；只在确认子进程停止后完成执行。"""
    attempt.state, attempt.result, attempt.error = state, result, error
    attempt.activity = dict(Task.Status.choices)[state]
    attempt.finished_at = timezone.now()
    attempt.save(update_fields=["state", "result", "error", "activity", "finished_at"])
    Task.objects.filter(pk=attempt.task_id).update(status=state)
    append_event(attempt, "finished", {"state": state, "error": error})


@transaction.atomic
def record_event(attempt_id, token, kind: str, data: dict) -> bool:
    task_id = Attempt.objects.values_list("task_id", flat=True).get(pk=attempt_id)
    Task.objects.select_for_update().get(pk=task_id)
    attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
    if attempt.state != "running" or attempt.claim_token != token or attempt.cancel_requested_at:
        return False
    if attempt.heartbeat_at < timezone.now() - timedelta(seconds=20):
        return False
    append_event(attempt, kind, data)
    attempt.activity = {"model": "模型正在处理", "tool_start": "正在调用工具", "tool_end": "工具已返回"}.get(kind, attempt.activity)
    attempt.save(update_fields=["activity"])
    return True


@transaction.atomic
def complete(attempt_id, token, *, state: str, result: str = "", error: str = "") -> bool:
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
        finish_locked(attempt, "interrupted", error="结果返回时租约已失效；结果未采纳。")
        return False
    if attempt.cancel_requested_at:
        state, result, error = "cancelled", "", "用户取消"
    finish_locked(attempt, state, result=result, error=error)
    return True
