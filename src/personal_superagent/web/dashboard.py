"""同源 SPA API；沿用 Session 与 CSRF，角色与设备凭证不进入前端。"""

import json
import mimetypes
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from django.utils.cache import patch_vary_headers
from django.db import transaction

from personal_superagent.tasks.forms import TaskForm
from personal_superagent.tasks.models import Task
from personal_superagent.tasks.services import create_task
from personal_superagent.devices.auth import new_pairing
from personal_superagent.devices.models import Device, Grant
from personal_superagent.execution.lifecycle import StateConflict
from personal_superagent.model_status import status as model_status

DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@login_required
@ensure_csrf_cookie
def index(request):
    if not (DIST / "index.html").is_file():
        return JsonResponse(
            {
                "error": "前端未构建，请执行 npm ci --prefix frontend && npm run build --prefix frontend"
            },
            status=503,
        )
    response = FileResponse(
        (DIST / "index.html").open("rb"), content_type="text/html; charset=utf-8"
    )
    response["Cache-Control"] = "no-store"
    return response


def asset(request, path):
    file = DIST / "assets" / path
    if (
        file.is_symlink()
        or not file.is_file()
        or not file.resolve().is_relative_to((DIST / "assets").resolve())
    ):
        raise Http404
    encoded = file.with_name(file.name + ".gz")
    use_gzip = False
    for item in request.headers.get("Accept-Encoding", "").split(","):
        parts = item.strip().split(";")
        if parts[0].lower() == "gzip":
            try:
                use_gzip = (
                    float(
                        next(
                            (
                                p.strip()[2:]
                                for p in parts[1:]
                                if p.strip().startswith("q=")
                            ),
                            "1",
                        )
                    )
                    > 0
                )
            except ValueError:
                pass
    use_gzip = use_gzip and encoded.is_file() and not encoded.is_symlink()
    response = FileResponse(
        (encoded if use_gzip else file).open("rb"),
        content_type=mimetypes.guess_type(file)[0] or "application/octet-stream",
    )
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    patch_vary_headers(response, ["Accept-Encoding"])
    if use_gzip:
        response["Content-Encoding"] = "gzip"
    return response


def task_data(task):
    attempt = task.attempts.order_by("-created_at").first()
    data = {
        "id": str(task.pk),
        "title": task.title,
        "description": task.description,
        "state": task.status,
        "created_at": task.created_at,
        "grant_id": str(task.local_grant_id) if task.local_grant_id else None,
        "source": None,
        "dispatch": task.dispatch,
        "release_id": str(task.release_id) if task.release_id else None,
        "agent": {
            "id": str(task.execution_agent_id),
            "name": task.execution_agent.name,
            "executor_kind": task.execution_agent.executor_kind,
            "device_id": str(task.execution_agent.device_id)
            if task.execution_agent.device_id
            else None,
        }
        if task.execution_agent_id
        else None,
        "routes": list(task.routes.values("state", "reason", "agent_id")),
    }
    from personal_superagent.intake.models import Confirmation

    source = Confirmation.objects.filter(task=task).first()
    if source:
        data["source"] = {
            "conversation_id": str(source.conversation_id),
            "version": source.version,
            "draft": source.draft,
            "message_ids": source.source_turn_ids,
        }
    data["attempts"] = list(
        task.attempts.order_by("-created_at").values(
            "id", "state", "mode", "error", "created_at"
        )
    )
    if attempt:
        from personal_superagent.happier.services import snapshot as external_snapshot
        data["attempt"] = {
            "id": str(attempt.pk),
            "executor": attempt.executor_kind,
            "external": external_snapshot(attempt),
            "state": attempt.state,
            "mode": attempt.mode,
            "activity": attempt.activity,
            "result": attempt.result,
            "error": attempt.error,
            "plan": attempt.plan,
            "started_at": attempt.started_at,
            "finished_at": attempt.finished_at,
            "stopped": attempt.process_stopped,
            "workflow_version": attempt.workflow_version,
            "execution_device_id": str(attempt.execution_device_id)
            if attempt.execution_device_id
            else None,
            "scope": attempt.input_snapshot.get("device"),
            "subtasks": list(
                attempt.subtasks.values(
                    "call_id", "role", "state", "description", "result"
                )
            ),
            "approvals": list(
                attempt.approvals.values("id", "decision", "version", "action")
            ),
            "artifacts": list(attempt.artifacts.values("id", "name")),
            "images": list(attempt.image_assets.values("id", "name")),
            "operations": list(
                attempt.local_operations.values(
                    "id", "tool", "arguments", "state", "reason"
                )
            ),
            "events": list(
                attempt.events.order_by("-sequence").values("sequence", "kind", "data")[
                    :100
                ]
            )[::-1],
        }
    return data


@login_required
@ensure_csrf_cookie
@never_cache
@require_http_methods(["GET", "POST"])
def api(request, action):
    try:
        data = json.loads(request.body or b"{}") if request.method == "POST" else {}
        if not isinstance(data, dict):
            raise ValueError("必须是 JSON 对象")
        if action == "bootstrap" and request.method == "GET":
            devices = []
            for device in Device.objects.filter(owner=request.user).prefetch_related(
                "grants"
            ):
                devices.append(
                    {
                        "id": str(device.pk),
                        "name": device.name,
                        "revoked": bool(device.revoked_at),
                        "online": bool(
                            device.last_seen
                            and device.last_seen
                            > timezone.now() - timedelta(seconds=20)
                            and not device.revoked_at
                        ),
                        "last_seen": device.last_seen,
                        "agents": list(
                            device.agentprofile_set.filter(enabled=True).values(
                                "name", "role", "modes", "tools", "last_seen"
                            )
                        ),
                        "grants": list(
                            device.grants.values(
                                "id",
                                "label",
                                "tools",
                                "revision",
                                "local_enabled",
                                "revoked_at",
                            )
                        ),
                    }
                )
            return JsonResponse(
                {
                    "user": request.user.username,
                    "real_enabled": settings.ALLOW_REAL_MODE
                    and model_status()["state"] == "ready",
                    "tasks": [
                        {
                            "id": str(t.pk),
                            "title": t.title,
                            "state": t.status,
                            "created_at": t.created_at,
                        }
                        for t in Task.objects.filter(owner=request.user, kind="task")[
                            :100
                        ]
                    ],
                    "devices": devices,
                }
            )
        if action == "task" and request.method == "GET":
            return JsonResponse(
                task_data(
                    get_object_or_404(
                        Task,
                        owner=request.user,
                        kind="task",
                        pk=UUID(request.GET["id"]),
                    )
                )
            )
        if action == "create" and request.method == "POST":
            if not isinstance(data.get("text"), str):
                raise ValueError("任务必须是文本")
            form = TaskForm(
                {
                    "title": str(data.get("title") or data.get("text", ""))[:120],
                    "description": data.get("text", ""),
                }
            )
            if not form.is_valid():
                raise ValueError("请填写有效任务需求，最多 10000 字")
            grant = None
            if data.get("grant_id"):
                grant = get_object_or_404(
                    Grant,
                    pk=UUID(data["grant_id"]),
                    device__owner=request.user,
                    device__revoked_at=None,
                    revoked_at=None,
                    local_enabled=True,
                )
            from personal_superagent.client.files import parts

            source = data.get("source_path", "input.md")
            if not isinstance(source, str) or not 1 <= len(source) <= 200:
                raise ValueError("材料路径长度不合法")
            parts(source)
            with transaction.atomic():
                task = create_task(user=request.user, form=form)
                task.local_grant, task.local_file = grant, source
                task.save(update_fields=["local_grant", "local_file"])
            return JsonResponse(task_data(task), status=201)
        if action == "pairing" and request.method == "POST":
            return JsonResponse(
                {"code": new_pairing(request.user), "expires_seconds": 600}
            )
        if action == "revoke" and request.method == "POST":
            if data.get("grant_id"):
                grant = get_object_or_404(
                    Grant, pk=UUID(data["grant_id"]), device__owner=request.user
                )
                grant.revoked_at = timezone.now()
                grant.save(update_fields=["revoked_at"])
            else:
                device = get_object_or_404(
                    Device, pk=UUID(data["device_id"]), owner=request.user
                )
                device.revoked_at = timezone.now()
                device.save(update_fields=["revoked_at"])
            return JsonResponse({"ok": True})
        raise ValueError("接口或 HTTP 方法不正确")
    except (ValueError, KeyError, TypeError, StateConflict):
        return JsonResponse({"error": "参数或状态无效，请刷新并检查授权"}, status=400)
