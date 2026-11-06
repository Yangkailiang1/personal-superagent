import json
import uuid
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from .models import LocalFile
from .services import files_for


@login_required
@never_cache
@require_POST
def open_file(request):
    try:
        if len(request.body) > 10000:
            raise ValueError("请求过大")
        data = json.loads(request.body)
        file = get_object_or_404(
            LocalFile, pk=data["id"], attempt__task__owner=request.user
        )
        if file.state != "available" or not any(
            x["device_online"] for x in files_for(file.attempt)
        ):
            return JsonResponse(
                {"error": "设备离线或文件已经变化，不能打开"}, status=409
            )
        file.open_requested = True
        file.open_request_id = uuid.uuid4()
        file.save(update_fields=["open_requested", "open_request_id"])
        return JsonResponse({"ok": True})
    except (ValueError, KeyError, TypeError, ValidationError):
        return JsonResponse({"error": "文件请求无效"}, status=400)
