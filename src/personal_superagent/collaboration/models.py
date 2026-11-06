"""编排业务事实；模型建议与用户授权分别留痕。"""

import uuid
from django.db import models
from django.conf import settings


class Question(models.Model):
    conversation = models.ForeignKey(
        "intake.Conversation", on_delete=models.CASCADE, related_name="choices"
    )
    version = models.PositiveIntegerField()
    prompt = models.TextField()
    options = models.JSONField()
    answer = models.TextField(blank=True)
    answered_at = models.DateTimeField(null=True)
    source_turn = models.ForeignKey("intake.Turn", on_delete=models.CASCADE)


class AgentProfile(models.Model):
    executor_kind = models.CharField(max_length=20, default="deepagents")
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    identity_key = models.CharField(max_length=160)
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=32)
    device = models.ForeignKey("devices.Device", null=True, on_delete=models.CASCADE)
    grant = models.ForeignKey("devices.Grant", null=True, on_delete=models.CASCADE)
    tools = models.JSONField(default=list)
    modes = models.JSONField(default=list)
    model_config = models.JSONField(default=dict)
    last_seen = models.DateTimeField(null=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "identity_key"], name="agent_identity_once"
            )
        ]


class Release(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        "intake.Conversation", on_delete=models.CASCADE, related_name="releases"
    )
    version = models.PositiveIntegerField()
    request_key = models.UUIDField()
    snapshot = models.JSONField()
    policy = models.JSONField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "version"], name="plan_release_revision"
            ),
            models.UniqueConstraint(
                fields=["conversation", "request_key"], name="plan_release_request"
            ),
        ]


class RouteDecision(models.Model):
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.CASCADE, related_name="routes"
    )
    agent = models.ForeignKey(AgentProfile, null=True, on_delete=models.SET_NULL)
    job = models.OneToOneField(
        "execution.Attempt", null=True, on_delete=models.SET_NULL
    )
    candidates = models.JSONField(default=list)
    reason = models.TextField(blank=True)
    state = models.CharField(max_length=24, default="queued")
    created_at = models.DateTimeField(auto_now_add=True)


class DeviceReceipt(models.Model):
    attempt = models.ForeignKey("execution.Attempt", on_delete=models.CASCADE)
    token = models.UUIDField()
    digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "token"], name="device_result_once"
            )
        ]


class Source(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=160)
    content = models.TextField()
    artifact = models.ForeignKey(
        "execution.Artifact", null=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)


class Page(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    slug = models.SlugField(max_length=100)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "slug"], name="wiki_page_owner")
        ]


class Revision(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    content = models.TextField()
    sources = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["page", "number"], name="wiki_revision_once"
            )
        ]


class Proposal(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job = models.OneToOneField(
        "execution.Attempt", null=True, on_delete=models.SET_NULL
    )
    changes = models.JSONField(default=list)
    report = models.TextField(blank=True)
    state = models.CharField(max_length=24, default="queued")
    request_key = models.UUIDField(default=uuid.uuid4)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "request_key"], name="wiki_proposal_request"
            )
        ]


class WikiLog(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    proposal = models.OneToOneField(Proposal, on_delete=models.CASCADE)
    entry = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class Schedule(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    enabled = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    mode = models.CharField(max_length=8, default="demo")
    version = models.PositiveIntegerField(default=1)


class Inspection(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    day = models.DateField()
    job = models.OneToOneField("execution.Attempt", on_delete=models.CASCADE)
    report = models.TextField(blank=True)
    calls = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "day"], name="inspection_daily_once"
            )
        ]


class ImageAsset(models.Model):
    attempt = models.ForeignKey(
        "execution.Attempt", on_delete=models.CASCADE, related_name="image_assets"
    )
    name = models.CharField(max_length=80)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["attempt", "name"], name="image_asset_once")
        ]
