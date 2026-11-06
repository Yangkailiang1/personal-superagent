"""一次执行是一份不可覆盖的输入和审计记录，不是 LangGraph checkpoint。"""
import uuid

from django.db import models
from django.db.models import Q

from personal_superagent.tasks.models import Task


class Attempt(models.Model):
    executor_kind = models.CharField(max_length=20, default="deepagents")
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attempts")
    execution_device = models.ForeignKey("devices.Device", null=True, on_delete=models.SET_NULL)
    request_key = models.UUIDField()
    state = models.CharField(max_length=24, choices=Task.Status.choices, default=Task.Status.QUEUED)
    mode = models.CharField(max_length=8, choices=[("demo", "离线演示"), ("real", "真实模型")])
    input_snapshot = models.JSONField()
    result = models.TextField(blank=True)
    error = models.TextField(blank=True)
    activity = models.CharField(max_length=200, blank=True)
    claim_token = models.UUIDField(null=True, editable=False)
    worker_id = models.UUIDField(null=True)
    hostname = models.CharField(max_length=200, blank=True)
    process_id = models.IntegerField(null=True)
    process_birth = models.FloatField(null=True)
    process_stopped = models.BooleanField(default=True)
    heartbeat_at = models.DateTimeField(null=True)
    cancel_requested_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    event_seq = models.PositiveIntegerField(default=0)
    workflow_version = models.CharField(max_length=32, blank=True)
    execution_action = models.CharField(max_length=16, default="start")
    plan = models.JSONField(default=list)
    checkpoint_id = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["task", "request_key"], name="attempt_request_once"),
            # 中断但没有确认进程停止，仍占据执行归属，阻止重试。
            models.UniqueConstraint(fields=["task"], condition=(
                Q(state__in=["queued", "running", "waiting_approval", "waiting_device"]) | Q(process_stopped=False)
            ), name="one_active_attempt_per_task"),
        ]


class RunEvent(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=32)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [models.UniqueConstraint(fields=["attempt", "sequence"], name="event_sequence_unique")]


class Approval(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="approvals")
    interrupt_id = models.CharField(max_length=100)
    action_index = models.PositiveIntegerField()
    action = models.JSONField()
    source_id = models.CharField(max_length=100)
    checkpoint_id = models.CharField(max_length=100)
    decision = models.CharField(max_length=16, default="pending")
    version = models.PositiveIntegerField(default=1)
    request_key = models.UUIDField(null=True)
    decided_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["attempt", "interrupt_id", "action_index"], name="approval_action_once")]


class Artifact(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="artifacts")
    source_id = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attempt", "source_id"], name="artifact_once")]


class SubTask(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="subtasks")
    call_id = models.CharField(max_length=100)
    role = models.CharField(max_length=40)
    description = models.TextField()
    namespace = models.CharField(max_length=300, blank=True)
    state = models.CharField(max_length=24, default="running")
    result = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attempt", "call_id"], name="subtask_call_once")]
