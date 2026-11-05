"""checkpoint 是恢复依据；业务表是受权限保护的展示投影，按稳定 ID 补齐。"""
from .models import Approval, Artifact, SubTask


def apply_snapshot_locked(attempt, data: dict) -> None:
    """调用方持有 Task/Attempt 行锁；不得在进程尚存活时读取/投影文件。"""
    checkpoint_id = data.get("checkpoint_id", "")
    if not checkpoint_id:
        raise ValueError("checkpoint 没有有效状态")
    attempt.checkpoint_id = checkpoint_id
    attempt.plan = data.get("plan", [])
    attempt.save(update_fields=["checkpoint_id", "plan"])
    for item in data.get("pending", []):
        Approval.objects.get_or_create(
            attempt=attempt, interrupt_id=item["interrupt_id"], action_index=item["index"],
            defaults={"action": item["action"], "source_id": item["source_id"], "checkpoint_id": checkpoint_id},
        )
    for source_id, document in data.get("documents", {}).items():
        approval = Approval.objects.filter(attempt=attempt, source_id=source_id, decision="approve").first()
        if approval is None or approval.action.get("args") != document:
            raise ValueError("产物缺少匹配的已批准记录")
        artifact, created = Artifact.objects.get_or_create(
            attempt=attempt, source_id=source_id, defaults={"name": document["name"], "content": document["content"]},
        )
        if not created and (artifact.name != document["name"] or artifact.content != document["content"]):
            raise ValueError("同一产物不能被旧结果覆盖")
    for item in data.get("subtasks", []):
        SubTask.objects.update_or_create(attempt=attempt, call_id=item["call_id"], defaults={
            key: item[key] for key in ["role", "description", "state", "result"]
        })
    from personal_superagent.devices.workflow import sync_requests_locked
    sync_requests_locked(attempt, data)


def update_activity_locked(attempt, kind: str, data: dict) -> None:
    if kind == "plan":
        attempt.plan = data.get("todos", [])
        attempt.save(update_fields=["plan"])
    elif kind == "subagent_start":
        SubTask.objects.get_or_create(attempt=attempt, call_id=data["call_id"], defaults={
            "role": data["role"], "description": data.get("description", ""),
        })
    elif kind == "subagent_end":
        SubTask.objects.filter(attempt=attempt, call_id=data["call_id"]).update(state=data["state"])
    if data.get("namespace") and data.get("parent_call_id"):
        SubTask.objects.filter(attempt=attempt, call_id=data["parent_call_id"]).update(namespace=data["namespace"])
