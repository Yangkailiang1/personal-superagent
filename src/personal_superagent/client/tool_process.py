"""只执行固定 Python 文件工具，不接收程序名、Shell 或任意代码。"""

import json
import sys
from .files import execute

if __name__ == "__main__":
    try:
        data = json.loads(sys.stdin.buffer.readline())
        result = {
            "ok": True,
            "data": execute(data["root"], data["tool"], data["arguments"]),
        }
    except (ValueError, OSError, UnicodeError, KeyError) as exc:
        # 不回传本机绝对路径或原始 OS 异常内容。
        result = {
            "ok": False,
            "error": "本地工具拒绝或执行失败（"
            + type(exc).__name__
            + "）：检查路径、权限、文件格式与是否已存在",
        }
    print(json.dumps(result, ensure_ascii=False))
