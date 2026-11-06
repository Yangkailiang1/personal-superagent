"""用户决定与模型执行分离：只写决定和排队，不在请求中运行模型。"""
import socket

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from personal_superagent.tasks.models import Task
from personal_superagent.tasks.services import get_task
from personal_superagent.workflow.checkpoints import CheckpointError
from .lifecycle import StateConflict, append_event
from .models import Approval, Attempt
from .projections import apply_snapshot_locked


def lock_attempt(user, task_id, attempt_id):
    get_task(user=user, task_id=task_id)
    task = Task.objects.select_for_update().get(pk=task_id, owner=user)
    return get_object_or_404(Attempt.objects.select_for_update(), pk=attempt_id, task=task)


def queue_locked(attempt, action):
    attempt.state = "queued"
    attempt.execution_action = action
    attempt.error = ""
    attempt.finished_at = None
    attempt.activity = "等待恢复执行"
    attempt.save(update_fields=["state", "execution_action", "error", "finished_at", "activity"])
    Task.objects.filter(pk=attempt.task_id).update(status="queued")
    append_event(attempt, "resume_queued", {"action": action})


@transaction.atomic
def decide(*, user, task_id, attempt_id, approval_id, expected_version: int, request_key, decision: str):
    attempt = lock_attempt(user, task_id, attempt_id)
    approval = get_object_or_404(Approval.objects.select_for_update(), pk=approval_id, attempt=attempt)
    if approval.request_key == request_key and approval.decision == decision:
        return approval
    if decision not in {"approve", "reject"}:
        raise StateConflict("只允许批准或拒绝")
    if attempt.state not in {"waiting_approval", "waiting_device"} or not attempt.process_stopped or attempt.cancel_requested_at:
        raise StateConflict("该执行当前不能审批")
    if approval.version != expected_version or approval.decision != "pending":
        raise StateConflict("审批已更新，请刷新页面")
    approval.decision, approval.request_key, approval.decided_at = decision, request_key, timezone.now()
    approval.version += 1
    approval.save(update_fields=["decision", "request_key", "decided_at", "version"])
    append_event(attempt, "approval_decided", {"approval_id": approval.pk, "decision": decision})
    from personal_superagent.devices.workflow import maybe_resume_locked
    maybe_resume_locked(attempt)
    return approval


@transaction.atomic
def resume(*, user, task_id, attempt_id):
    attempt = lock_attempt(user, task_id, attempt_id)
    if attempt.state == "queued" and attempt.execution_action != "start":
        return attempt
    if attempt.state != "interrupted" or not attempt.process_stopped or attempt.cancel_requested_at:
        raise StateConflict("只可恢复已确认停止、未取消的中断执行")
    if attempt.executor_kind == "happier":
        raise StateConflict("Claude 中断结果需先核实，本版请新建重试，不透明重放会话")
    if attempt.execution_device_id:
        # 用户显式恢复；由原设备读取原 checkpoint，缺失/不兼容会失败，绝不从头执行。
        queue_locked(attempt,"continue")
        return attempt
    if attempt.hostname != socket.gethostname():
        raise StateConflict("checkpoint 只能在原执行主机恢复")
    try:
        from personal_superagent.execution.versions import module_for
        data = module_for(attempt.workflow_version).inspect_checkpoint(attempt)
    except (CheckpointError, ValueError) as exc:
        raise StateConflict(str(exc)) from None
    apply_snapshot_locked(attempt, data)
    if data["pending"] and attempt.approvals.filter(checkpoint_id=attempt.checkpoint_id, decision="pending").exists():
        attempt.state, attempt.activity = "waiting_approval", "等待用户审批"
        attempt.save(update_fields=["state", "activity"])
        Task.objects.filter(pk=task_id).update(status="waiting_approval")
        append_event(attempt, "approval_recovered", {})
    elif data.get("local_requests"):
        attempt.state = "waiting_device"
        attempt.save(update_fields=["state"])
        Task.objects.filter(pk=task_id).update(status="waiting_device")
        from personal_superagent.devices.workflow import maybe_resume_locked
        maybe_resume_locked(attempt)
    else:
        queue_locked(attempt, "resume" if data["pending"] else "continue")
    return attempt
