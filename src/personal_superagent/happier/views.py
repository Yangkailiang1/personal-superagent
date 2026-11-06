import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .models import Repository
from .services import decide


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def endpoint(request, action):
    try:
        if action == "repositories" and request.method == "GET":
            return JsonResponse(
                {
                    "items": list(
                        Repository.objects.filter(
                            device__owner=request.user,
                            enabled=True,
                            device__revoked_at=None,
                        ).values(
                            "id",
                            "agent_id",
                            "label",
                            "baseline",
                            "policy",
                            "version",
                            "device_id",
                            "agent__enabled",
                        )
                    )
                }
            )
        if action == "decide" and request.method == "POST":
            if len(request.body) > 10000:
                raise ValueError("请求过大")
            p = decide(request.user, json.loads(request.body))
            return JsonResponse({"id": p.pk, "applied": p.applied})
        raise ValueError("接口或方法无效")
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "请求无效或状态已变化，请刷新"}, status=409)
