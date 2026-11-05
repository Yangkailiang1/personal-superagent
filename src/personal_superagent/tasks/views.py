from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

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
    return render(request, "tasks/detail.html", {
        "task": get_task(user=request.user, task_id=task_id),
    })
