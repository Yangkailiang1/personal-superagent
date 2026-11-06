"""不可变原料与知识修订；模型只能生成 Proposal，确认由用户接口完成。"""

import json
import uuid
from zoneinfo import ZoneInfo
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from personal_superagent.collaboration.models import (
    Source,
    Page,
    Revision,
    Proposal,
    WikiLog,
    Schedule,
    Inspection,
)
from personal_superagent.collaboration.jobs import enqueue_job, Output
from personal_superagent.tasks.models import Task
from personal_superagent.execution.lifecycle import StateConflict


def snapshot(user, ids):
    if not isinstance(ids, list) or not ids or len(ids) > 20:
        raise ValueError("最多二十份材料")
    sources = list(
        Source.objects.filter(owner=user, pk__in=ids).values("id", "title", "content")
    )
    if len(sources) != len(set(ids)):
        raise ValueError("来源不存在或越权")
    pages = []
    for page in Page.objects.filter(owner=user):
        revision = page.revisions.filter(number=page.revision).first()
        if revision:
            pages.append(
                {
                    "slug": page.slug,
                    "revision": page.revision,
                    "content": revision.content,
                    "sources": revision.sources,
                }
            )
    if (
        sum(len(s["content"]) for s in sources) + sum(len(p["content"]) for p in pages)
        > 100000
    ):
        raise ValueError("本次材料过多，请分批整理")
    return {"sources": [{**s, "id": str(s["id"])} for s in sources], "pages": pages}


@transaction.atomic
def propose(user, data):
    key = uuid.UUID(data["request_key"])
    old = Proposal.objects.filter(owner=user, request_key=key).first()
    if old:
        return old
    context = snapshot(user, data["source_ids"])
    job = enqueue_job(user, "knowledge", context, data.get("mode", "demo"))
    return Proposal.objects.create(owner=user, job=job, request_key=key)


def project(attempt):
    if attempt.input_snapshot["kind"] == "inspection":
        item = Inspection.objects.select_for_update().get(job=attempt)
        if attempt.state == "succeeded":
            result = json.loads(attempt.result)
            item.report = result["report"]
            item.calls = result["calls"]
        else:
            item.report = attempt.error
            item.calls = attempt.events.filter(kind="model").count()
        item.save()
        return
    proposal = Proposal.objects.select_for_update().get(job=attempt)
    if attempt.state != "succeeded":
        proposal.state = "failed"
        proposal.report = attempt.error
        proposal.save()
        return
    decoded = json.loads(attempt.result)
    decoded.pop("calls", None)
    data = Output.model_validate(decoded)
    sources = {s["id"] for s in attempt.input_snapshot["sources"]}
    if any(not set(change.sources) <= sources for change in data.changes):
        raise ValueError("知识来源越权")
    if len({c.slug for c in data.changes}) != len(data.changes):
        raise ValueError("同次修改不能重复页面")
    proposal.changes = [c.model_dump() for c in data.changes]
    proposal.report = data.report
    proposal.state = "review"
    proposal.save()


@transaction.atomic
def approve(user, id):
    proposal = get_object_or_404(
        Proposal.objects.select_for_update(), pk=id, owner=user
    )
    if proposal.state == "approved":
        return proposal
    if proposal.state != "review":
        raise StateConflict("建议尚不能确认")
    for change in proposal.changes:
        page, _ = Page.objects.get_or_create(owner=user, slug=change["slug"])
        page = Page.objects.select_for_update().get(pk=page.pk)
        if page.revision != change["base"]:
            raise StateConflict("知识页已有新修订，请重新整理")
        sources = Source.objects.filter(owner=user, pk__in=change["sources"])
        if sources.count() != len(set(change["sources"])):
            raise ValueError("来源已失效")
        Revision.objects.create(
            page=page,
            number=page.revision + 1,
            content=change["content"],
            sources=change["sources"],
        )
        page.revision += 1
        page.save(update_fields=["revision"])
    proposal.state = "approved"
    proposal.save(update_fields=["state"])
    WikiLog.objects.create(owner=user, proposal=proposal, entry=proposal.report)
    return proposal


def query(user, text):
    if not isinstance(text, str) or not 1 <= len(text) <= 500:
        raise ValueError("查询长度无效")
    result = []
    for page in Page.objects.filter(owner=user):
        revision = page.revisions.get(number=page.revision) if page.revision else None
        if revision and (
            text.lower() in revision.content.lower()
            or text.lower() in page.slug.lower()
        ):
            result.append(
                {
                    "slug": page.slug,
                    "revision": revision.number,
                    "content": revision.content,
                    "sources": revision.sources,
                }
            )
    return result[:20]


@transaction.atomic
def schedule_due(now=None):
    now = now or timezone.now()
    for schedule in (
        Schedule.objects.select_for_update(skip_locked=True)
        .filter(enabled=True)
        .select_related("owner")
    ):
        local = now.astimezone(ZoneInfo(schedule.timezone))
        if (
            local.hour < 9
            or Inspection.objects.filter(
                owner=schedule.owner, day=local.date()
            ).exists()
        ):
            continue
        pending = list(
            Task.objects.filter(owner=schedule.owner, kind="task")
            .exclude(status__in=["succeeded", "cancelled"])
            .values("id", "title", "status")[:100]
        )
        used = {
            source
            for page in Page.objects.filter(owner=schedule.owner)
            for revision in page.revisions.filter(number=page.revision)
            for source in revision.sources
        }
        context = {
            "tasks": [{**t, "id": str(t["id"])} for t in pending],
            "unorganized": list(
                Source.objects.filter(owner=schedule.owner)
                .exclude(pk__in=used)
                .values("title")[:100]
            ),
        }
        try:
            job = enqueue_job(schedule.owner, "inspection", context, schedule.mode)
        except ValueError:
            # 配置失效也记录当天失败，不在每个调度 tick 重试。
            from personal_superagent.execution.models import Attempt

            task = Task.objects.create(
                owner=schedule.owner,
                kind="inspection",
                title="巡检未运行",
                description="模型配置未就绪",
                status="failed",
            )
            job = Attempt.objects.create(
                task=task,
                request_key=uuid.uuid4(),
                mode=schedule.mode,
                state="failed",
                input_snapshot={"kind": "inspection"},
                error="模型配置未就绪，未调用模型",
            )
        Inspection.objects.create(
            owner=schedule.owner,
            day=local.date(),
            job=job,
            report=job.error if job.state == "failed" else "",
        )
