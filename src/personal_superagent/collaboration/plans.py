"""用户发布是权限关卡；依赖与资源在服务端校验，不能相信模型 UUID。"""

import uuid
from django.db import transaction
from django.shortcuts import get_object_or_404
from personal_superagent.intake.models import Conversation
from personal_superagent.intake.services import owned, ensure_idle
from personal_superagent.execution.lifecycle import StateConflict
from personal_superagent.tasks.models import Task
from .models import Release
from .schema import Plan, Policy


@transaction.atomic
def publish(user, id, data):
    c = Conversation.objects.select_for_update().get(pk=owned(user, id).pk)
    key = uuid.UUID(data["request_key"])
    old = c.releases.filter(request_key=key).first()
    if old:
        if old.version != data["version"]:
            raise StateConflict("请求版本改变")
        return old
    if c.version != data["version"]:
        raise StateConflict("Plan 已更新，请刷新")
    old = c.releases.filter(version=c.version).first()
    if old:
        return old
    ensure_idle(c)
    if c.choices.filter(answered_at=None).exists():
        raise StateConflict("请先回答问题")
    plan = Plan.model_validate(c.draft)
    policy = Policy.model_validate(data["policy"])
    if not plan.steps or plan.questions:
        raise StateConflict("Plan 尚未完成")
    if plan.assumptions and data.get("accept_assumptions") is not True:
        raise StateConflict("需要明确接受假设")
    from .routing import provision, validate_step

    provision(user)
    for step in plan.steps:
        validate_step(user, step, policy)
    release = Release.objects.create(
        conversation=c,
        version=c.version,
        request_key=key,
        snapshot=plan.model_dump(),
        policy=policy.model_dump(),
    )
    tasks = {}
    for step in plan.steps:
        task = Task.objects.create(
            owner=user,
            title=step.title,
            description=step.goal
            + "\n交付："
            + str(step.deliverables)
            + "\n验收："
            + str(step.acceptance),
            release=release,
            dispatch=step.model_dump(),
            local_grant_id=step.grant_id or None,
            local_file=step.source_path,
        )
        tasks[step.key] = task
    for step in plan.steps:
        tasks[step.key].dependencies.set([tasks[k] for k in step.depends_on])
    return release


@transaction.atomic
def change_route(user, id, data):
    task = get_object_or_404(
        Task.objects.select_for_update(), pk=id, owner=user, release__isnull=False
    )
    if task.status != "pending" or task.attempts.exists():
        raise StateConflict("已有执行不能修改冻结目标，请新建 Plan 修订")
    if task.dispatch != data["expected"]:
        raise StateConflict("路由已变更")
    from .routing import validate_step
    from .schema import Step

    updated = {**task.dispatch, "agent_id": data["agent_id"]}
    validate_step(
        user, Step.model_validate(updated), Policy.model_validate(task.release.policy)
    )
    task.routes.filter(state="failed").update(state="superseded")
    task.dispatch = updated
    task.execution_agent = None
    task.save(update_fields=["dispatch", "execution_agent"])
    return task
