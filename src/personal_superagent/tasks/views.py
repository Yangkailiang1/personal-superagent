from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from uuid import uuid4
from django.conf import settings

from .forms import TaskForm
from .services import create_task, get_task, list_tasks


@login_required
@require_http_methods(["GET", "POST"])
def task_list(request):
    form = TaskForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        task = create_task(user=request.user, form=form)
        return redirect("task_detail", task_id=task.id)
    return render(request, "tasks/list.html", {
        "form": form, "tasks": list_tasks(user=request.user),
    })


@login_required
@require_GET
def task_detail(request, task_id):
    task = get_task(user=request.user, task_id=task_id)
    attempts = list(task.attempts.order_by("-created_at"))
    active = next((a for a in attempts if a.state in {"queued", "running", "waiting_approval"}), None)
    unsafe = any(not a.process_stopped for a in attempts)
    return render(request, "tasks/detail.html", {
        "task": task, "attempts": attempts, "latest": attempts[0] if attempts else None,
        "active": active, "unsafe": unsafe, "request_key": uuid4(),
        "can_start": task.status == "pending",
        "can_retry": task.status in {"failed", "cancelled", "interrupted"} and not unsafe,
        "can_resume": task.status == "interrupted" and not unsafe and bool(attempts and attempts[0].workflow_version),
        "real_enabled": settings.ALLOW_REAL_MODE,
    })
