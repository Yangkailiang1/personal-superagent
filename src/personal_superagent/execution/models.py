"""一次执行是一份不可覆盖的输入和审计记录，不是 LangGraph checkpoint。"""
import uuid

from django.db import models
from django.db.models import Q

from personal_superagent.tasks.models import Task


class Attempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attempts")
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

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["task", "request_key"], name="attempt_request_once"),
            # 中断但没有确认进程停止，仍占据执行归属，阻止重试。
            models.UniqueConstraint(fields=["task"], condition=(
                Q(state__in=["queued", "running"]) | Q(process_stopped=False)
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
