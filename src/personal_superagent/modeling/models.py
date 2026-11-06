"""设备能力与本地文件追踪；此应用没有文件内容字段或上传接口。"""

import uuid
from django.db import models


class Capability(models.Model):
    device = models.OneToOneField("devices.Device", on_delete=models.CASCADE)
    agent = models.OneToOneField("collaboration.AgentProfile", on_delete=models.CASCADE)
    grant_id = models.UUIDField()
    config = models.JSONField()
    enabled = models.BooleanField(default=True)


class LocalFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        "execution.Attempt", on_delete=models.CASCADE, related_name="local_files"
    )
    device = models.ForeignKey("devices.Device", on_delete=models.CASCADE)
    grant_id = models.UUIDField()
    path = models.CharField(max_length=200)
    media_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    state = models.CharField(max_length=16, default="available")
    checked_at = models.DateTimeField(auto_now=True)
    open_requested = models.BooleanField(default=False)
    open_request_id = models.UUIDField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "path"], name="local_file_attempt_path"
            )
        ]
