"""接待会话与业务草稿；模型调用复用 Attempt 队列，而不是另建调度器。"""

import uuid
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=120, default="新需求")
    draft = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)


class Turn(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="turns"
    )
    attempt = models.OneToOneField("execution.Attempt", on_delete=models.CASCADE)
    text = models.TextField()
    reply = models.TextField(blank=True)
    base_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class Confirmation(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="confirmations"
    )
    request_key = models.UUIDField()
    version = models.PositiveIntegerField()
    source_turn_ids = models.JSONField(default=list)
    draft = models.JSONField()
    task = models.OneToOneField(
        "tasks.Task", on_delete=models.CASCADE, related_name="source_confirmation"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "version"], name="confirm_revision_once"
            ),
            models.UniqueConstraint(
                fields=["conversation", "request_key"], name="confirm_request_once"
            ),
        ]
