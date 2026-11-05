"""设备凭证只保存哈希；本地路径永不上传，云端只认识授权别名与工具。"""

import uuid

from django.conf import settings
from django.db import models


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    token_hash = models.CharField(max_length=64)
    session = models.UUIDField(null=True)
    last_seen = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Pairing(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)


class Grant(models.Model):
    id = models.UUIDField(primary_key=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="grants")
    label = models.CharField(max_length=80)
    tools = models.JSONField(default=list)
    revision = models.PositiveIntegerField(default=1)
    local_enabled = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True)


class LocalOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        "execution.Attempt", on_delete=models.CASCADE, related_name="local_operations"
    )
    grant = models.ForeignKey(Grant, on_delete=models.RESTRICT)
    source_id = models.CharField(max_length=100)
    interrupt_id = models.CharField(max_length=100)
    checkpoint_id = models.CharField(max_length=100)
    tool = models.CharField(max_length=40)
    arguments = models.JSONField()
    grant_revision = models.PositiveIntegerField()
    state = models.CharField(max_length=24, default="pending")
    result = models.JSONField(default=dict)
    reason = models.CharField(max_length=300, blank=True)
    lease_hash = models.CharField(max_length=64, blank=True)
    lease_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "source_id"], name="local_call_once"
            )
        ]
