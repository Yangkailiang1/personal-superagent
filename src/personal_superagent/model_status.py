"""模型验证状态仅对应配置指纹，不保存或输出 Key。"""

import hashlib
import json
import os
from django.conf import settings


def fingerprint():
    return hashlib.sha256(
        json.dumps(
            [
                os.environ.get(x, "")
                for x in ("MODEL_NAME", "MODEL_BASE_URL", "MODEL_API_KEY")
            ]
        ).encode()
    ).hexdigest()


def status_path():
    from personal_superagent.workflow.checkpoints import runtime_root

    return runtime_root() / "model-status.json"


def status():
    configured = all(
        os.environ.get(x, "").strip() for x in ("MODEL_NAME", "MODEL_API_KEY")
    )
    state = "unconfigured"
    if configured:
        state = "unverified"
        try:
            saved = json.loads(status_path().read_text())
            if saved["fingerprint"] == fingerprint():
                state = saved["state"]
        except (OSError, ValueError, KeyError):
            pass
    return {
        "state": state,
        "enabled": settings.ALLOW_REAL_MODE,
        "model": os.environ.get("MODEL_NAME", ""),
        "labels": {
            "unconfigured": "未配置",
            "unverified": "待验证",
            "ready": "可用",
            "failed": "连接失败",
        },
    }
