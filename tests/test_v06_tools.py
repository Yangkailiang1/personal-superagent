"""工具协议测试使用固定响应，不发送搜索、生图或 MCP 付费请求。"""

import base64
import io
import json
import os
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
import pytest
from PIL import Image
from langchain_core.tools import tool
from personal_superagent.collaboration.toolkit import registry, validate_mcp


def test_search_context_and_image_budget(tmp_path):
    out = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(out, "PNG")
    raw = out.getvalue()
    fake = SimpleNamespace(
        images=SimpleNamespace(
            generate=lambda **kw: SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(raw).decode())]
            )
        ),
        close=lambda: None,
    )
    with (
        patch.dict(
            os.environ,
            {
                "TAVILY_API_KEY": "fake-search-not-real",
                "IMAGE_API_KEY": "fake-image-not-real",
                "IMAGE_MODEL_NAME": "fake",
            },
        ),
        patch("openai.OpenAI", return_value=fake),
    ):
        with registry(
            "image_designer",
            ["inspect_context", "generate_image"],
            {"max_images": 1},
            tmp_path / "images",
        ) as tools:
            inspect = next(t for t in tools if t.name == "inspect_context")
            assert "fake-image-not-real" not in str(inspect.invoke({}))
            image = next(t for t in tools if t.name == "generate_image")
            message = image.invoke(
                {
                    "name": "generate_image",
                    "args": {"prompt": "白色示例"},
                    "id": "image",
                    "type": "tool_call",
                }
            )
            name = message.artifact["images"][0]["name"]
            assert (tmp_path / "images" / name).read_bytes() == raw
            with pytest.raises(ValueError):
                image.invoke({"prompt": "第二张"})


def test_mcp_tool_whitelist_lifecycle_and_sync_bridge(tmp_path):
    @tool
    async def search_docs(query: str) -> str:
        """只读搜索测试服务。"""
        return "docs:" + query

    @tool
    async def untrusted_delete(path: str) -> str:
        """不允许注册的删除工具。"""
        pytest.fail("未授权工具不能执行")

    cfg = [
        {
            "name": "test",
            "transport": "streamable_http",
            "url": "https://example.invalid/mcp",
            "allowed_tools": ["search_docs"],
        }
    ]
    with (
        patch.dict(os.environ, {"MCP_CONFIG": json.dumps(cfg)}),
        patch(
            "langchain_mcp_adapters.client.MultiServerMCPClient.get_tools",
            new=AsyncMock(return_value=[search_docs, untrusted_delete]),
        ),
    ):
        with registry(
            "researcher", ["mcp__search_docs"], {}, tmp_path / "images"
        ) as tools:
            assert [t.name for t in tools] == ["mcp__search_docs"]
            assert tools[0].invoke({"query": "agent"}) == "docs:agent"
    with pytest.raises(ValueError):
        validate_mcp(
            [
                {
                    "name": "bad",
                    "transport": "stdio",
                    "command": "sh",
                    "allowed_tools": ["execute"],
                }
            ]
        )


def test_tavily_protocol_and_search_cap(tmp_path):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps(
                {
                    "results": [
                        {
                            "title": "原始来源",
                            "url": "https://example.test/source",
                            "content": "支持材料",
                        }
                    ]
                }
            ).encode()

    with (
        patch.dict(os.environ, {"TAVILY_API_KEY": "fake-search-key"}),
        patch(
            "personal_superagent.collaboration.toolkit.urlopen", return_value=Response()
        ) as network,
    ):
        with registry(
            "researcher", ["tavily_search"], {}, tmp_path / "images"
        ) as tools:
            for _ in range(3):
                assert (
                    tools[0].invoke({"query": "agent"})["results"][0]["url"]
                    == "https://example.test/source"
                )
            with pytest.raises(ValueError):
                tools[0].invoke({"query": "fourth"})
            assert network.call_count == 3

def test_management_calls_stop_at_eight():
    from personal_superagent.collaboration.jobs import Bound
    calls=[]
    middleware=Bound(lambda kind,data:calls.append(data))
    class Request:
        tools=[]
        def override(self,**kw):return self
    request=Request()
    for _ in range(8):middleware.wrap_model_call(request,lambda r:None)
    with pytest.raises(ValueError):middleware.wrap_model_call(request,lambda r:pytest.fail('第九次不能访问供应商'))
    assert len(calls)==8
