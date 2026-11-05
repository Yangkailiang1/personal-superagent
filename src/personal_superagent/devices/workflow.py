"""本地请求由原生 interrupt 转成持久化操作；只有确定结果才能恢复图。"""

from .models import Grant, LocalOperation


def scope_for(task) -> dict | None:
    if not task.local_grant_id:
        return None
    grant = Grant.objects.select_related("device").get(pk=task.local_grant_id)
    if (
        grant.device.owner_id != task.owner_id
        or grant.device.revoked_at
        or grant.revoked_at
        or not grant.local_enabled
    ):
        raise ValueError("设备目录授权已撤销或不属于当前用户")
    return {
        "grant_id": str(grant.pk),
        "device_id": str(grant.device_id),
        "device_name": grant.device.name,
        "revision": grant.revision,
        "label": grant.label,
        "tools": grant.tools,
        "source_path": task.local_file,
    }


def sync_requests_locked(attempt, snapshot):
    scope = attempt.input_snapshot.get("device")
    for item in snapshot.get("local_requests", []):
        if not scope or item["grant_id"] != scope["grant_id"]:
            raise ValueError("本地工具请求缺少冻结授权范围")
        grant = Grant.objects.select_related("device").get(pk=scope["grant_id"])
        if grant.device.owner_id != attempt.task.owner_id:
            raise ValueError("设备归属错误")
        operation, created = LocalOperation.objects.get_or_create(
            attempt=attempt,
            source_id=item["source_id"],
            defaults={
                "grant": grant,
                "tool": item["tool"],
                "arguments": item["arguments"],
                "grant_revision": scope["revision"],
                "interrupt_id": item["interrupt_id"],
                "checkpoint_id": snapshot["checkpoint_id"],
            },
        )
        if not created:
            if (
                operation.tool != item["tool"]
                or operation.arguments != item["arguments"]
                or str(operation.grant_id) != scope["grant_id"]
                or operation.grant_revision != scope["revision"]
            ):
                raise ValueError("工具调用 ID 已存在但参数或授权发生变化，拒绝复用结果")
            operation.interrupt_id, operation.checkpoint_id = (
                item["interrupt_id"],
                snapshot["checkpoint_id"],
            )
            operation.save(update_fields=["interrupt_id", "checkpoint_id"])


def maybe_resume_locked(attempt) -> bool:
    if (
        attempt.state not in {"waiting_device", "waiting_approval"}
        or not attempt.process_stopped
        or attempt.cancel_requested_at
    ):
        return False
    if attempt.approvals.filter(
        checkpoint_id=attempt.checkpoint_id, decision="pending"
    ).exists():
        return False
    if (
        attempt.local_operations.filter(checkpoint_id=attempt.checkpoint_id)
        .exclude(state__in=["succeeded", "failed"])
        .exists()
    ):
        return False
    # 普通文档审批仍沿用原语义，不能把没有任何 interrupt 的等待意外排队。
    if (
        not attempt.approvals.filter(checkpoint_id=attempt.checkpoint_id).exists()
        and not attempt.local_operations.filter(
            checkpoint_id=attempt.checkpoint_id
        ).exists()
    ):
        return False
    from personal_superagent.execution.approvals import queue_locked

    queue_locked(attempt, "resume")
    return True
