"""终端配置本机工具，凭证只保存在本机私密文件。"""

import getpass
import json
import os
from .worker_agent import model_environment


def configure(root):
    cfg = model_environment(root)
    fields = [
        ("TAVILY_API_KEY", "Tavily Key"),
        ("IMAGE_API_KEY", "生图 Key"),
        ("IMAGE_MODEL_NAME", "生图模型"),
        ("IMAGE_BASE_URL", "生图 HTTPS Base URL"),
    ]
    for key, label in fields:
        value = getpass.getpass(label + "（隐藏输入，留空保留）：").strip()
        if value:
            if "\n" in value:
                raise ValueError("配置不得换行")
            cfg[key] = value
    file = input("本机 MCP JSON 配置路径（留空保留）：").strip()
    if file:
        from pathlib import Path
        from personal_superagent.collaboration.toolkit import validate_mcp

        value = json.loads(Path(file).expanduser().read_text())
        validate_mcp(value, local=True)
        cfg["MCP_CONFIG"] = json.dumps(value)
    fd = os.open(root / "model.json", os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f)
    print("本机工具配置已保存；修改配置后重新 agent-check，未发送搜索或生图请求。")
