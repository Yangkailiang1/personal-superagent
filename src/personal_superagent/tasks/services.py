"""任务权限集中在业务入口，未来 API 也复用同样的归属检查。"""
from django.contrib.auth.models import AbstractBaseUser
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from .forms import TaskForm
from .models import Task


def list_tasks(*, user: AbstractBaseUser) -> QuerySet[Task]:
    """先限定归属再查询；不可仅靠前端隐藏其他用户任务。"""
    return Task.objects.filter(owner=user)


def get_task(*, user: AbstractBaseUser, task_id) -> Task:
    # 他人的 ID 和不存在的 ID 都返回 404，避免暴露任务是否存在。
    return get_object_or_404(list_tasks(user=user), pk=task_id)


def create_task(*, user: AbstractBaseUser, form: TaskForm) -> Task:
    """输入已校验表单，返回持久化任务；不在 HTTP 请求里调用 Agent。"""
    task = form.save(commit=False)
    task.owner = user
    task.save()
    return task
