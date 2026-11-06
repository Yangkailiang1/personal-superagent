"""显式调用两次模型：工具调用 + 工具结果响应；不自动开启真实任务。"""

import json
import os
from django.core.management.base import BaseCommand, CommandError
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from personal_superagent.models import build_model
from personal_superagent.model_status import fingerprint, status_path


class Command(BaseCommand):
    help = "显式验证真实模型工具调用，会产生少量 API 费用；配置不完整时不会发送请求"

    def handle(self, *args, **options):
        model = build_model(demo=False)

        @tool
        def connectivity_probe(value: str) -> str:
            """无副作用连通性检查，请传入 probe-ok。"""
            return value

        saved = {"fingerprint": fingerprint(), "state": "failed"}
        try:
            bound = model.bind_tools(
                [connectivity_probe], tool_choice="connectivity_probe"
            )
            messages = [
                HumanMessage(
                    content="Call connectivity_probe with value probe-ok. Then return the tool result."
                )
            ]
            first = bound.invoke(messages)
            if (
                len(first.tool_calls) != 1
                or first.tool_calls[0]["name"] != "connectivity_probe"
                or first.tool_calls[0]["args"] != {"value": "probe-ok"}
            ):
                raise ValueError()
            final = model.invoke(
                [
                    *messages,
                    first,
                    ToolMessage(
                        content="probe-ok", tool_call_id=first.tool_calls[0]["id"]
                    ),
                ]
            )
            if "probe-ok" not in str(final.content):
                raise ValueError()
            saved["state"] = "ready"
        except Exception:
            self.stderr.write(
                "模型工具调用验证失败；未输出供应商原始错误，请检查接口、模型及工具支持。"
            )
        path = status_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(saved, f)
        os.replace(temporary, path)
        if saved["state"] != "ready":
            raise CommandError("真实模型尚不可用")
        self.stdout.write(
            "模型工具调用验证通过（2 次请求）；请重新加载工作台查看状态。"
        )
