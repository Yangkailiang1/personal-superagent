"""PostgreSQL 领取协议：短事务、全局额度锁、领取凭证、租约与隔离。"""

import socket
import uuid
from datetime import timedelta

from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from personal_superagent.tasks.models import Task
from .lifecycle import append_event, finish_locked
from .models import Attempt

LEASE_SECONDS = 20
GLOBAL_LIMIT = 2


def require_postgres() -> None:
    if connection.vendor != "postgresql":
        raise CommandError(
            "Worker 只支持 PostgreSQL；不会回退 SQLite 或在网页请求中执行。"
        )


@transaction.atomic
def claim_next(worker_id, device=None) -> Attempt | None:
    require_postgres()
    # 所有 Worker 共享同一事务级锁，避免分别计数后同时突破全局额度。
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [70202002])
    occupied = Attempt.objects.filter(
        Q(state="running") | Q(process_stopped=False)
    ).count()
    if occupied >= GLOBAL_LIMIT:
        return None
    query = Task.objects.select_for_update(skip_locked=True).filter(
        status="queued", attempts__state="queued", attempts__execution_device=device
    )
    if device is not None:
        if Attempt.objects.filter(
            execution_device=device, process_stopped=False
        ).exists():
            return None
    task = query.order_by("created_at", "id").first()
    if task is None:
        return None
    attempt = Attempt.objects.select_for_update().get(task=task, state="queued")
    attempt.state = "running"
    attempt.worker_id = worker_id
    attempt.hostname = "device:" + str(device.pk) if device else socket.gethostname()
    attempt.claim_token = uuid.uuid4()
    attempt.process_id = attempt.process_birth = None
    attempt.process_stopped = False
    attempt.started_at = attempt.started_at or timezone.now()
    attempt.heartbeat_at = timezone.now()
    attempt.activity = "准备执行子进程"
    attempt.save()
    task.status = "running"
    task.save(update_fields=["status"])
    append_event(attempt, "claimed", {"mode": attempt.mode})
    return attempt


@transaction.atomic
def heartbeat(attempt_id, token) -> bool:
    # 不能仅靠 token 继续续租；已超时的租约不能被一个迟到心跳复活。
    now = timezone.now()
    return bool(
        Attempt.objects.filter(
            pk=attempt_id,
            claim_token=token,
            state="running",
            heartbeat_at__gte=now - timedelta(seconds=LEASE_SECONDS),
        ).update(heartbeat_at=now)
    )


def expire_leases() -> None:
    ids = list(
        Attempt.objects.filter(
            state="running",
            heartbeat_at__lt=timezone.now() - timedelta(seconds=LEASE_SECONDS),
        ).values_list("id", "task_id")
    )
    for attempt_id, task_id in ids:
        with transaction.atomic():
            Task.objects.select_for_update().get(pk=task_id)
            attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
            if (
                attempt.state == "running"
                and attempt.heartbeat_at
                < timezone.now() - timedelta(seconds=LEASE_SECONDS)
            ):
                finish_locked(
                    attempt,
                    "interrupted",
                    error="Worker 心跳过期；旧结果已隔离，等待确认进程停止。",
                )
