from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, FileResponse
from io import BytesIO
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from personal_superagent.tasks.services import get_task
from .lifecycle import StateConflict, enqueue, request_cancel
from .models import Attempt
from .models import Artifact
from .approvals import decide, resume
from .templatetags.markdown import markdown


@login_required
@require_POST
def start(request, task_id):
    try:
        key = UUID(request.POST.get("request_key", ""))
        enqueue(user=request.user, task_id=task_id, request_key=key,
                mode=request.POST.get("mode", ""), retry=request.POST.get("action") == "retry")
    except (ValueError, StateConflict) as exc:
        message = str(exc) if isinstance(exc, StateConflict) else "缺少有效的启动请求键。"
        return JsonResponse({"error": message}, status=409 if isinstance(exc, StateConflict) else 400)
    return redirect("task_detail", task_id=task_id)


@login_required
@require_POST
def cancel(request, task_id, attempt_id):
    request_cancel(user=request.user, task_id=task_id, attempt_id=attempt_id)
    return redirect("task_detail", task_id=task_id)


@login_required
@require_GET
def events(request, task_id, attempt_id):
    task = get_task(user=request.user, task_id=task_id)
    attempt = get_object_or_404(Attempt, pk=attempt_id, task=task)
    try:
        after = int(request.GET.get("after", "0"))
        if after < 0:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "after 必须为非负整数"}, status=400)
    rows = list(attempt.events.filter(sequence__gt=after, sequence__lte=attempt.event_seq).values("sequence", "kind", "data", "created_at")[:200])
    cursor = rows[-1]["sequence"] if rows else after
    response = JsonResponse({
        "attempt_id": str(attempt.pk), "task_id": str(task.pk),
        "state": attempt.state, "activity": attempt.activity, "mode": attempt.mode,
        "process_stopped": attempt.process_stopped, "cancel_requested": bool(attempt.cancel_requested_at),
        "result": attempt.result, "error": attempt.error,
        "result_html": str(markdown(attempt.result)), "plan": attempt.plan,
        "subtasks": list(attempt.subtasks.values("call_id", "role", "state", "namespace")),
        "events": rows, "cursor": cursor, "has_more": cursor < attempt.event_seq,
    })
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def decision(request, task_id, attempt_id, approval_id):
    try:
        decide(user=request.user, task_id=task_id, attempt_id=attempt_id, approval_id=approval_id,
               expected_version=int(request.POST.get("version", "")),
               request_key=UUID(request.POST.get("request_key", "")), decision=request.POST.get("decision", ""))
    except ValueError as exc:
        return JsonResponse({"error": str(exc) if isinstance(exc, StateConflict) else "审批参数不合法"}, status=409 if isinstance(exc, StateConflict) else 400)
    return redirect("task_detail", task_id=task_id)


@login_required
@require_POST
def restore(request, task_id, attempt_id):
    try:
        resume(user=request.user, task_id=task_id, attempt_id=attempt_id)
    except StateConflict as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    return redirect("task_detail", task_id=task_id)


@login_required
@require_GET
def artifact(request, task_id, attempt_id, artifact_id):
    task = get_task(user=request.user, task_id=task_id)
    item = get_object_or_404(Artifact, pk=artifact_id, attempt_id=attempt_id, attempt__task=task)
    if request.GET.get("download") == "1":
        return FileResponse(BytesIO(item.content.encode()), as_attachment=True, filename=item.name, content_type="text/markdown; charset=utf-8")
    from django.shortcuts import render
    return render(request, "tasks/artifact.html", {"artifact": item, "task": task})
