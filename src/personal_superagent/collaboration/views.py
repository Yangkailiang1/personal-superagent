"""会话 Cookie/CSRF 的用户控制面，与设备 Bearer 控制面分离。"""

import json
from zoneinfo import ZoneInfo
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.db import transaction
from personal_superagent.execution.lifecycle import StateConflict
from .models import AgentProfile, Source, Page, Proposal, Schedule, Inspection, WikiLog


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def endpoint(request, action):
    from personal_superagent.knowledge import services as wiki

    try:
        data = (
            json.loads(request.body or b"{}")
            if request.method == "POST"
            else request.GET
        )
        if action == "tools" and request.method == "GET":
            from .toolkit import catalog

            return JsonResponse({"items": catalog()})
        if action == "agents" and request.method == "GET":
            return JsonResponse(
                {
                    "items": list(
                        AgentProfile.objects.filter(owner=request.user).values(
                            "id",
                            "name",
                            "role",
                            "device_id",
                            "grant_id",
                            "tools",
                            "modes",
                            "enabled",
                            "last_seen",
                        )
                    )
                }
            )
        if action == "wiki" and request.method == "GET":
            pages = []
            for page in Page.objects.filter(owner=request.user):
                latest = page.revisions.filter(number=page.revision).first()
                pages.append(
                    {
                        "id": page.pk,
                        "slug": page.slug,
                        "revision": page.revision,
                        "content": latest.content if latest else "",
                        "sources": latest.sources if latest else [],
                        "history": list(
                            page.revisions.values(
                                "number", "content", "sources", "created_at"
                            )
                        ),
                    }
                )
            return JsonResponse(
                {
                    "sources": list(
                        Source.objects.filter(owner=request.user).values(
                            "id", "title", "content", "artifact_id"
                        )
                    ),
                    "pages": pages,
                    "proposals": list(
                        Proposal.objects.filter(owner=request.user).values(
                            "id", "state", "changes", "report"
                        )
                    ),
                    "log": list(
                        WikiLog.objects.filter(owner=request.user).values(
                            "id", "entry", "created_at"
                        )
                    ),
                    "inspections": list(
                        Inspection.objects.filter(owner=request.user).values(
                            "id", "day", "report", "calls", "job__state"
                        )
                    ),
                    "schedule": list(
                        Schedule.objects.filter(owner=request.user).values(
                            "enabled", "timezone", "mode", "version"
                        )
                    ),
                }
            )
        if action == "query" and request.method == "GET":
            return JsonResponse({"items": wiki.query(request.user, data["q"])})
        if request.method != "POST":
            raise ValueError("方法错误")
        if action == "source":
            title = data["title"]
            content = data.get("content", "")
            artifact = None
            if data.get("artifact_id"):
                from personal_superagent.execution.models import Artifact

                artifact = get_object_or_404(
                    Artifact, pk=data["artifact_id"], attempt__task__owner=request.user
                )
                content = artifact.content
            if (
                not isinstance(title, str)
                or not 1 <= len(title) <= 160
                or not isinstance(content, str)
                or not 1 <= len(content) <= 16000
            ):
                raise ValueError("来源长度无效")
            source = Source.objects.create(
                owner=request.user, title=title, content=content, artifact=artifact
            )
            return JsonResponse({"id": str(source.pk)})
        if action == "propose":
            return JsonResponse({"id": wiki.propose(request.user, data).pk})
        if action == "approve":
            return JsonResponse({"id": wiki.approve(request.user, data["id"]).pk})
        if action == "ack-stop":
            from personal_superagent.execution.models import Attempt
            from personal_superagent.tasks.models import Task
            from personal_superagent.execution.lifecycle import append_event

            with transaction.atomic():
                original = get_object_or_404(
                    Attempt,
                    pk=data["id"],
                    task__owner=request.user,
                    execution_device__isnull=False,
                )
                Task.objects.select_for_update().get(pk=original.task_id)
                attempt = Attempt.objects.select_for_update().get(pk=original.pk)
                if (
                    attempt.state not in {"interrupted", "cancelled"}
                    or data.get("confirmed") is not True
                ):
                    raise StateConflict("必须先在设备上确认旧进程已经停止")
                attempt.process_stopped = True
                attempt.save(update_fields=["process_stopped"])
                append_event(
                    attempt,
                    "user_confirmed_device_stopped",
                    {"independent_verification": False},
                )
            return JsonResponse({"ok": True})
        if action == "route":
            from .plans import change_route

            return JsonResponse(
                {"id": str(change_route(request.user, data["id"], data).pk)}
            )
        if action == "schedule":
            ZoneInfo(data["timezone"])
            if data["mode"] not in {"demo", "real"} or not isinstance(
                data["enabled"], bool
            ):
                raise ValueError("巡检配置无效")
            with transaction.atomic():
                schedule, _ = Schedule.objects.get_or_create(owner=request.user)
                schedule = Schedule.objects.select_for_update().get(pk=schedule.pk)
                if schedule.version != data["version"]:
                    raise StateConflict("巡检设置已更新")
                schedule.enabled = data["enabled"]
                schedule.timezone = data["timezone"]
                schedule.mode = data["mode"]
                schedule.version += 1
                schedule.save()
            return JsonResponse({"ok": True})
        raise ValueError("未知操作")
    except StateConflict as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "参数或授权无效"}, status=400)
