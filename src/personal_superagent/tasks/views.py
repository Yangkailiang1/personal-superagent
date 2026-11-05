"""旧书签只做导航兼容，任务操作统一进入新版工作台。"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_GET

from .services import get_task


@login_required
@require_GET
def task_list(request):
    return redirect("dashboard")


@login_required
@require_GET
def task_detail(request, task_id):
    # 先校验归属，旧链接也不能借重定向探查其他用户任务。
    task = get_task(user=request.user, task_id=task_id)
    return redirect(f"{reverse('dashboard')}?task={task.pk}")
