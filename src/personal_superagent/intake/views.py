import json
from uuid import UUID
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from personal_superagent.execution.lifecycle import StateConflict, request_cancel
from .models import Conversation, Turn
from .services import owned, send, edit, confirm


def serialize(c):
    return {
        "id": str(c.pk),
        "title": c.title,
        "draft": c.draft,
        "version": c.version,
        "turns": [
            {
                "id": t.pk,
                "text": t.text,
                "reply": t.reply,
                "state": t.attempt.state,
                "error": t.attempt.error,
                "mode": t.attempt.mode,
                "stopped": t.attempt.process_stopped,
            }
            for t in c.turns.select_related("attempt")
        ],
        "confirmed": list(c.confirmations.values("version", "task_id")),
        "questions": list(
            c.choices.order_by("id").values(
                "id", "prompt", "options", "answer", "answered_at"
            )
        ),
        "releases": list(c.releases.values("id", "version", "policy")),
    }


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def endpoint(request, action):
    try:
        data = (
            json.loads(request.body or b"{}")
            if request.method == "POST"
            else request.GET
        )
        if not isinstance(data, dict) and request.method == "POST":
            raise ValueError()
        if action == "conversations":
            if request.method == "GET":
                return JsonResponse(
                    {
                        "items": list(
                            Conversation.objects.filter(owner=request.user)
                            .order_by("-created_at")
                            .values("id", "title", "version")
                        )
                    }
                )
            from personal_superagent.collaboration.routing import provision

            provision(request.user)
            c = Conversation.objects.create(
                owner=request.user, plan_mode=data.get("style") == "plan"
            )
            return JsonResponse(serialize(c), status=201)
        id = UUID(data["id"])
        if action == "conversation" and request.method == "GET":
            return JsonResponse(serialize(owned(request.user, id)))
        if request.method != "POST":
            raise ValueError()
        if action == "answer":
            from personal_superagent.collaboration.questions import answer

            answer(request.user, id, data)
        elif action == "publish":
            from personal_superagent.collaboration.plans import publish

            release = publish(request.user, id, data)
            return JsonResponse(
                {
                    "release_id": str(release.pk),
                    "task_ids": [str(t.pk) for t in release.tasks.all()],
                }
            )
        elif action == "send":
            send(request.user, id, data)
        elif action == "edit":
            edit(request.user, id, data)
        elif action == "confirm":
            return JsonResponse({"task_id": str(confirm(request.user, id, data).pk)})
        elif action == "cancel":
            turn = (
                owned(request.user, id)
                .turns.select_related("attempt")
                .get(pk=data["turn_id"])
            )
            request_cancel(
                user=request.user,
                task_id=turn.attempt.task_id,
                attempt_id=turn.attempt_id,
            )
        else:
            raise ValueError()
        return JsonResponse(serialize(owned(request.user, id)))
    except StateConflict as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except (
        ValueError,
        KeyError,
        TypeError,
        Conversation.DoesNotExist,
        Turn.DoesNotExist,
    ):
        return JsonResponse({"error": "参数无效，请检查消息和草稿"}, status=400)
