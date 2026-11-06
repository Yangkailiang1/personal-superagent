import json
from uuid import UUID

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache

from .auth import authenticate, pair
from .models import LocalOperation
from django.core.exceptions import ObjectDoesNotExist
from .protocol import poll, report, validate_lease


@csrf_exempt
@never_cache
@require_POST
def endpoint(request, action):
    """仅设备 Bearer 身份，不接受浏览器 Session；不为 Cookie 接口关闭 CSRF。"""
    try:
        if len(request.body) > (
            15 * 1024 * 1024 if action == "agent-control" else 160000
        ):
            raise ValueError("请求超过大小限制")
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError("必须使用 JSON 对象")
        if data.get("protocol", 1) != 1:
            raise ValueError("设备协议版本不兼容")
        if action == "pair":
            name = data.get("name", "")
            if not isinstance(name, str) or not 1 <= len(name) <= 80:
                raise ValueError("设备名称长度应为 1—80")
            if not isinstance(data.get("code"), str):
                raise ValueError("绑定码不合法")
            device, token = pair(data["code"], name)
            return JsonResponse({"device_id": str(device.pk), "token": token})
        device = authenticate(request)
        if device is None:
            return JsonResponse({"error": "设备凭证无效或已撤销"}, status=401)
        if action.startswith("agent-"):
            from personal_superagent.collaboration.device_jobs import (
                hello,
                claim,
                control,
            )

            if action == "agent-hello":
                return JsonResponse(hello(device, data))
            if action == "agent-claim":
                return JsonResponse(claim(device))
            if action == "agent-control":
                return JsonResponse(control(device, data))
            raise ValueError("未知设备接口")
        if not isinstance(data.get("session"), str):
            raise ValueError("会话结构不合法")
        if action in {"connect", "poll"}:
            result = poll(
                device.pk,
                UUID(data["session"]),
                data.get("grants", []),
                connect=action == "connect",
            )
            return JsonResponse(result)
        if UUID(data["session"]) != device.session:
            raise ValueError("设备会话已失效")
        if not isinstance(data.get("id"), str) or not isinstance(
            data.get("lease"), str
        ):
            raise ValueError("操作结构不合法")
        UUID(data["id"])
        if action == "check":
            validate_lease(device, data["id"], data["lease"])
        elif action == "report":
            if not isinstance(data.get("result"), dict):
                raise ValueError("结果必须是对象")
            report(device, data["id"], data["lease"], data["state"], data["result"])
        else:
            raise ValueError("未知设备接口")
        return JsonResponse({"ok": True})
    except (
        ValueError,
        KeyError,
        TypeError,
        LocalOperation.DoesNotExist,
        ObjectDoesNotExist,
    ):
        return JsonResponse(
            {"error": "参数、绑定码、会话或操作授权无效，请检查配置"}, status=400
        )
