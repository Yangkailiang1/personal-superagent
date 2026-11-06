"""会话锁串行化编辑/确认；调用本身进入原有 Attempt，复用领取、租约和进程监督。"""

import json
from uuid import UUID
from django.db import transaction
from django.conf import settings
from django.shortcuts import get_object_or_404
from personal_superagent.tasks.models import Task
from personal_superagent.execution.models import Attempt
from personal_superagent.execution.lifecycle import StateConflict, append_event
from .models import Conversation, Turn, Confirmation
from personal_superagent.collaboration.schema import Plan as Draft


def owned(user, id):
    return get_object_or_404(Conversation, pk=id, owner=user)


def ensure_idle(conversation):
    if (
        conversation.turns.filter(attempt__state__in=["queued", "running"]).exists()
        or conversation.turns.filter(attempt__process_stopped=False).exists()
    ):
        raise StateConflict("会话仍有活动调用，请等待或取消；旧进程必须先确认停止。")


@transaction.atomic
def send(user, id, data):
    c = Conversation.objects.select_for_update().get(pk=owned(user, id).pk)
    key = UUID(data["request_key"])
    existing = c.turns.filter(attempt__request_key=key).first()
    if existing:
        if existing.text != data["text"] or existing.attempt.mode != data["mode"]:
            raise StateConflict("请求键不能更改内容")
        return existing
    ensure_idle(c)
    if data.get("upgrade_plan") is True and not c.plan_mode:
        c.plan_mode = True
        c.save(update_fields=["plan_mode"])
    if c.version != data["version"]:
        raise StateConflict("草稿已更新，请刷新")
    text, mode = data["text"], data["mode"]
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 6000:
        raise ValueError("消息长度应为 1—6000")
    if mode not in {"demo", "real"}:
        raise ValueError("模式错误")
    if mode == "real":
        from personal_superagent.model_status import status

        if not settings.ALLOW_REAL_MODE or status()["state"] != "ready":
            raise StateConflict("请先完成真实模型配置与验证")
    if c.choices.filter(answered_at=None).exists():
        raise StateConflict("请先回答当前选择题")
    messages = []
    for turn in c.turns.all():
        messages.append({"role": "user", "content": turn.text})
        if turn.reply:
            messages.append({"role": "assistant", "content": turn.reply})
    if sum(len(m["content"]) for m in messages) + len(text) > 24000:
        raise StateConflict("会话已达上下文上限，请新建会话；历史不会删除。")
    task = Task.objects.create(
        owner=user, kind="intake", title="需求接待", description=text, status="queued"
    )
    from personal_superagent.workflow.checkpoints import execution_config

    attempt = Attempt.objects.create(
        task=task,
        request_key=key,
        mode=mode,
        input_snapshot={
            "kind": "intake",
            "text": text,
            "messages": messages,
            "draft": c.draft,
            "model_config": execution_config(mode),
            "plan_mode": c.plan_mode,
            "answers": list(
                c.choices.exclude(answered_at=None).values("prompt", "answer")
            ),
            "agents": [
                {
                    "id": str(a.pk),
                    "name": a.name,
                    "role": a.role,
                    "tools": a.tools,
                    "grant_id": str(a.grant_id) if a.grant_id else "",
                    "device_id": str(a.device_id) if a.device_id else "",
                }
                for a in __import__(
                    "personal_superagent.collaboration.models",
                    fromlist=["AgentProfile"],
                ).AgentProfile.objects.filter(owner=user, enabled=True)
            ],
            "repositories": list(
                __import__("personal_superagent.happier.models", fromlist=["Repository"])
                .Repository.objects.filter(device__owner=user, enabled=True, agent__enabled=True)
                .values("id", "agent_id", "label", "baseline", "policy", "version")
            ),
            "tasks": [
                {"id": str(t.pk), "title": t.title, "status": t.status}
                for t in Task.objects.filter(release__conversation=c)[:30]
            ],
            "knowledge": __import__(
                "personal_superagent.knowledge.services", fromlist=["query"]
            ).query(user, text[:500]),
        },
    )
    turn = Turn.objects.create(
        conversation=c, attempt=attempt, text=text, base_version=c.version
    )
    c.title = text[:120]
    c.save(update_fields=["title"])
    append_event(attempt, "queued", {"role": "intake", "mode": mode})
    return turn


@transaction.atomic
def edit(user, id, data):
    c = Conversation.objects.select_for_update().get(pk=owned(user, id).pk)
    ensure_idle(c)
    if c.version != data["version"]:
        raise StateConflict("草稿版本冲突")
    draft = Draft.model_validate(data["draft"])
    draft.description()
    c.draft = draft.model_dump()
    c.version += 1
    c.save()
    return c


@transaction.atomic
def confirm(user, id, data):
    c = Conversation.objects.select_for_update().get(pk=owned(user, id).pk)
    key = UUID(data["request_key"])
    old = c.confirmations.filter(request_key=key).first()
    if old:
        if old.version != data["version"]:
            raise StateConflict("请求键不能更改版本")
        return old.task
    if c.version != data["version"]:
        raise StateConflict("草稿版本冲突")
    ensure_idle(c)
    previous = c.confirmations.filter(version=c.version).first()
    if previous:
        return previous.task
    draft = Draft.model_validate(c.draft)
    if draft.questions:
        raise StateConflict("请先解决待确认问题")
    if draft.assumptions and data.get("accept_assumptions") is not True:
        raise StateConflict("请明确接受假设")
    grant = None
    if data.get("grant_id"):
        from personal_superagent.devices.models import Grant

        grant = get_object_or_404(
            Grant,
            pk=UUID(data["grant_id"]),
            device__owner=user,
            revoked_at=None,
            local_enabled=True,
            device__revoked_at=None,
        )
    source = data.get("source_path", "input.md")
    from personal_superagent.client.files import parts

    if not isinstance(source, str) or not 1 <= len(source) <= 200:
        raise ValueError("材料路径无效")
    parts(source)
    task = Task.objects.create(
        owner=user,
        title=draft.title,
        description=draft.description(),
        local_grant=grant,
        local_file=source,
    )
    Confirmation.objects.create(
        conversation=c,
        request_key=key,
        version=c.version,
        draft=c.draft,
        task=task,
        source_turn_ids=list(c.turns.values_list("id", flat=True)),
    )
    return task


def project_result(attempt):
    """与 Attempt 终态同事务投影；编辑被占用拦截，旧版本结果不能覆盖新草稿。"""
    turn = Turn.objects.select_related("conversation").get(attempt=attempt)
    c = Conversation.objects.select_for_update().get(pk=turn.conversation_id)
    if attempt.state != "succeeded":
        return
    try:
        result = json.loads(attempt.result)
        draft = (
            Draft.model_validate(result["draft"]).model_dump()
            if result["draft"]
            else c.draft
        )
        if c.version != turn.base_version:
            raise ValueError("版本冲突")
        turn.reply = str(result["reply"])[:10000]
        turn.save(update_fields=["reply"])
        if result.get("question"):
            from personal_superagent.collaboration.schema import Choice
            from personal_superagent.collaboration.models import Question

            choice = Choice.model_validate(result["question"])
            if c.choices.filter(answered_at=None).exists():
                raise ValueError("已有未回答问题")
            Question.objects.create(
                conversation=c,
                version=c.version + 1,
                prompt=choice.prompt,
                options=choice.options,
                source_turn=turn,
            )
        c.draft = draft
        c.version += 1
        c.save(update_fields=["draft", "version"])
    except (ValueError, KeyError, TypeError):
        attempt.state, attempt.error, attempt.activity = (
            "failed",
            "接待结果校验失败，原草稿未覆盖",
            "接待结果校验失败",
        )
        attempt.save(update_fields=["state", "error", "activity"])
        Task.objects.filter(pk=attempt.task_id).update(status="failed")
