"""外部运行事实与业务任务分开保存，运行回执不能自行批准业务计划。"""

import uuid
from django.db import models
from personal_superagent.devices.models import Device
from personal_superagent.collaboration.models import AgentProfile
from personal_superagent.execution.models import Attempt


class Repository(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    agent = models.OneToOneField(AgentProfile, on_delete=models.CASCADE)
    label = models.CharField(max_length=100)
    baseline = models.CharField(max_length=40)
    policy = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    enabled = models.BooleanField(default=True)


class ExternalRun(models.Model):
    attempt = models.OneToOneField(
        Attempt, on_delete=models.CASCADE, related_name="external_run"
    )
    instance = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    session_id = models.CharField(max_length=160, blank=True)
    cursor = models.PositiveIntegerField(default=0)
    report = models.JSONField(default=dict)
    receipt_digest = models.CharField(max_length=64, blank=True)


class Permission(models.Model):
    run = models.ForeignKey(
        ExternalRun, on_delete=models.CASCADE, related_name="permissions"
    )
    request_id = models.CharField(max_length=160)
    tool = models.CharField(max_length=100)
    arguments = models.JSONField()
    version = models.PositiveIntegerField(default=1)
    decision = models.CharField(max_length=16, default="pending")
    request_key = models.UUIDField(null=True)
    applied = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "request_id"], name="external_permission_once"
            )
        ]
