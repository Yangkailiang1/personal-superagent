"""看板是业务记录的投影，列状态由后端统一决定。"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.core.paginator import Paginator
from personal_superagent.tasks.models import Task
from personal_superagent.intake.models import Conversation
from personal_superagent.model_status import status

COLUMNS = [
    ("draft", "待确认"),
    ("pending", "待启动"),
    ("queued", "排队中"),
    ("running", "执行中"),
    ("attention", "待处理"),
    ("succeeded", "已完成"),
]


def card(task):
    attempt = task.attempts.order_by("-created_at").first()
    column = (
        task.status
        if task.status in {"pending", "queued", "running", "succeeded"}
        else "attention"
    )
    activity = attempt.activity if attempt else "等待用户启动"
    reason = attempt.error if attempt else ""
    if attempt and task.status == "waiting_device":
        unknown = attempt.local_operations.filter(state="uncertain").exists()
        activity = "操作结果未知，需人工核实" if unknown else "等待本地设备执行"
        scope = attempt.input_snapshot.get("device") or {}
        reason = f"{scope.get('device_name', '')} / {scope.get('label', '')}"
    if task.release_id and task.status == "pending":
        if task.dependencies.exclude(status="succeeded").exists():
            activity = "依赖任务尚未成功交付"
        elif task.routes.filter(state="failed").exists():
            column = "attention"
            activity = "路由失败，请调整计划或执行目标"
            reason = task.routes.filter(state="failed").last().reason
        else:
            activity = "等待路由或执行资源（指定设备离线时保持等待）"
            if task.dispatch.get('role')=='modeler':
                activity="等待在线、已授权且模型就绪的 Blender 工作 Agent"
    return {
        "agent": task.execution_agent.name if task.execution_agent_id else "未分派",
        "route_reason": task.routes.order_by("-id").first().reason
        if task.routes.exists()
        else "",
        "id": str(task.pk),
        "kind": "task",
        "title": task.title,
        "column": column,
        "state": task.status,
        "mode": attempt.mode if attempt else None,
        "activity": activity,
        "reason": reason,
        "started_at": attempt.started_at if attempt else None,
        "created_at": task.created_at,
    }


@login_required
@never_cache
@require_GET
def dashboard(request):
    try:
        page = int(request.GET.get("page", 1))
        if page < 1:
            raise ValueError()
    except ValueError:
        return JsonResponse({"error": "页码无效"}, status=400)
    query, mode, column = (
        request.GET.get("q", ""),
        request.GET.get("mode", ""),
        request.GET.get("column", ""),
    )
    history = request.GET.get("history") == "1"
    tasks = Task.objects.filter(
        owner=request.user, kind="task", title__icontains=query
    ).prefetch_related("attempts")
    tasks = (
        tasks.filter(status="cancelled")
        if history
        else tasks.exclude(status="cancelled")
    )
    # 按最新 Attempt 筛选，重试后不能按旧模式误归类。
    from django.db.models import OuterRef, Subquery
    from personal_superagent.execution.models import Attempt

    tasks = tasks.annotate(
        latest_mode=Subquery(
            Attempt.objects.filter(task_id=OuterRef("pk"))
            .order_by("-created_at")
            .values("mode")[:1]
        )
    )
    if mode:
        tasks = tasks.filter(latest_mode=mode)
    if column and column != "draft":
        states = (
            ["waiting_device", "waiting_approval", "failed", "interrupted", "cancelled"]
            if column == "attention"
            else [column]
        )
        tasks = tasks.filter(status__in=states)
    if column == "draft":
        tasks = tasks.none()
    items = [card(t) for t in tasks]
    if not history and not mode and column in {"", "draft"}:
        for c in Conversation.objects.filter(
            owner=request.user, title__icontains=query
        ):
            if (
                c.draft
                and not c.confirmations.filter(version=c.version).exists()
                and not c.releases.filter(version=c.version).exists()
            ):
                items.append(
                    {
                        "id": str(c.pk),
                        "kind": "draft",
                        "title": c.draft.get("title", c.title),
                        "column": "draft",
                        "state": "draft",
                        "mode": None,
                        "activity": "等待核对草稿",
                        "reason": "；".join(c.draft.get("questions", [])),
                        "created_at": c.created_at,
                        "started_at": None,
                    }
                )
    items.sort(key=lambda x: (x["created_at"], x["id"]), reverse=True)
    paginator = Paginator(items, 30)
    current = paginator.get_page(page)
    return JsonResponse(
        {
            "columns": COLUMNS,
            "counts": {
                key: sum(1 for item in items if item["column"] == key)
                for key, _ in COLUMNS
            },
            "items": list(current),
            "total": paginator.count,
            "page": current.number,
            "pages": paginator.num_pages,
            "model": status(),
        }
    )
