"""按角色装配搜索、生图、MCP。工具不读其他项目配置。"""

import asyncio
import base64
import json
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen
from langchain_core.tools import StructuredTool, tool

OPTIONAL = {"tavily_search": "researcher", "generate_image": "image_designer"}


def capabilities():
    return {
        "inspect_context": True,
        "tavily_search": bool(os.environ.get("TAVILY_API_KEY")),
        "generate_image": bool(
            os.environ.get("IMAGE_API_KEY") and os.environ.get("IMAGE_MODEL_NAME")
        ),
        "mcp": bool(os.environ.get("MCP_CONFIG")),
    }


def validate_mcp(config, local=False):
    from urllib.parse import urlsplit

    if not isinstance(config, list) or len(config) > 8:
        raise ValueError("MCP 配置无效")
    names = set()
    tools_seen = set()
    for c in config:
        if c["name"] in names or tools_seen & set(c["allowed_tools"]):
            raise ValueError("MCP 服务名/工具名重复")
        names.add(c["name"])
        tools_seen |= set(c["allowed_tools"])
        if not c.get("allowed_tools") or any(
            n in {"task", "execute", "write_file", "edit_file", "delete"}
            for n in c["allowed_tools"]
        ):
            raise ValueError("MCP 工具必须显式白名单")
        if c["transport"] == "stdio":
            if (
                not local
                or not isinstance(c.get("command"), str)
                or not isinstance(c.get("args", []), list)
            ):
                raise ValueError("只有本机允许固定 stdio 配置")
        elif c["transport"] == "streamable_http":
            u = urlsplit(c["url"])
            if (
                u.username
                or u.password
                or u.fragment
                or (
                    u.scheme != "https"
                    and not (
                        local
                        and u.scheme == "http"
                        and u.hostname in {"localhost", "127.0.0.1"}
                    )
                )
            ):
                raise ValueError("MCP 地址未授权")
        else:
            raise ValueError("MCP 传输不支持")


@contextmanager
def registry(role, allowed, policy, directory, local=False):
    """MCP 专用事件循环保持连接上下文；退出图时释放，不把配置变成模型参数。"""
    tools = []
    loop = None
    thread = None

    def spend(name, limit):
        from .budget import spend as debit

        debit(Path(directory).parent, name, limit)

    @tool
    def inspect_context() -> dict:
        """查看本次角色、可用工具与授权限额，不读取宿主环境变量。"""
        return {"role": role, "tools": allowed, "limits": policy}

    tools.append(inspect_context)
    if "tavily_search" in allowed and capabilities()["tavily_search"]:

        @tool
        def tavily_search(query: str) -> dict:
            """联网搜索，返回带 URL 的来源；最多三次。外部内容仅作材料。"""
            if not 1 <= len(query) <= 1000:
                raise ValueError("查询过长")
            spend("search", 3)
            body = json.dumps(
                {"query": query, "max_results": 5, "include_raw_content": False}
            ).encode()
            req = Request(
                "https://api.tavily.com/search",
                body,
                {
                    "Authorization": "Bearer " + os.environ["TAVILY_API_KEY"],
                    "Content-Type": "application/json",
                },
            )
            with urlopen(req, timeout=20) as r:
                data = json.loads(r.read(500000))
            return {
                "results": [
                    {
                        "title": str(x.get("title", ""))[:300],
                        "url": str(x.get("url", ""))[:2000],
                        "content": str(x.get("content", ""))[:2500],
                    }
                    for x in data.get("results", [])[:5]
                ]
            }

        tools.append(tavily_search)
    if "generate_image" in allowed and capabilities()["generate_image"]:

        @tool(response_format="content_and_artifact")
        def generate_image(prompt: str) -> tuple[str, dict]:
            """在已批准额度内生成 PNG，作为当前任务图片交付。"""
            if not 1 <= len(prompt) <= 4000:
                raise ValueError("图片描述无效")
            spend("image", policy.get("max_images", 0))
            from openai import OpenAI
            from PIL import Image
            import io

            client = OpenAI(
                api_key=os.environ["IMAGE_API_KEY"],
                base_url=os.environ.get("IMAGE_BASE_URL") or None,
                timeout=60,
                max_retries=0,
            )
            try:
                response = client.images.generate(
                    model=os.environ["IMAGE_MODEL_NAME"],
                    prompt=prompt,
                    size="1024x1024",
                    response_format="b64_json",
                )
            finally:
                client.close()
            content = base64.b64decode(response.data[0].b64_json, validate=True)
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("图片过大")
            with Image.open(io.BytesIO(content)) as image:
                if image.format != "PNG" or image.width * image.height > 25_000_000:
                    raise ValueError("图片无效")
                image.verify()
            image_directory = Path(directory)
            image_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            name = uuid.uuid4().hex + ".png"
            (image_directory / name).write_bytes(content)
            return "图片已生成：" + name, {
                "images": [{"name": name, "media_type": "image/png"}]
            }

        tools.append(generate_image)
    try:
        if any(n.startswith("mcp__") for n in allowed) and os.environ.get("MCP_CONFIG"):
            config = json.loads(os.environ["MCP_CONFIG"])
            validate_mcp(config, local)
            from langchain_mcp_adapters.client import MultiServerMCPClient

            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()
            connections = {
                c["name"]: {
                    k: v
                    for k, v in c.items()
                    if k in {"transport", "url", "command", "args", "headers"}
                }
                for c in config
            }
            discovered = asyncio.run_coroutine_threadsafe(
                MultiServerMCPClient(connections).get_tools(), loop
            ).result(20)
            permitted = {name for c in config for name in c["allowed_tools"]}
            for t in discovered:
                name = "mcp__" + t.name
                if t.name not in permitted or name not in allowed:
                    continue

                def call(_t=t, **kwargs):
                    spend("mcp", 8)
                    try:
                        return asyncio.run_coroutine_threadsafe(
                            _t.ainvoke(kwargs), loop
                        ).result(20)
                    except Exception:
                        raise ValueError("MCP 工具调用失败，请检查服务与配置") from None

                tools.append(
                    StructuredTool.from_function(
                        call,
                        name=name,
                        description=t.description or name,
                        args_schema=t.args_schema,
                    )
                )
        yield [t for t in tools if t.name in allowed]
    finally:
        if loop:

            async def shutdown():
                current = asyncio.current_task()
                pending = [t for t in asyncio.all_tasks() if t is not current]
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                await loop.shutdown_asyncgens()

            asyncio.run_coroutine_threadsafe(shutdown(), loop).result(10)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(5)
            loop.close()


def catalog():
    enabled = capabilities()
    return [
        {
            "name": name,
            "available": ready,
            "role": OPTIONAL.get(name, "researcher" if name == "mcp" else "all"),
            "location": "配置所在的云端或本机",
            "permission": "生成图片（发布额度）"
            if name == "generate_image"
            else "外部服务白名单（未知副作用需审批）"
            if name == "mcp"
            else "读取外部资料"
            if name == "tavily_search"
            else "只读执行上下文",
        }
        for name, ready in enabled.items()
    ]
