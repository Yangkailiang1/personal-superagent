"""生成本项目专用配置，不读取已有 .env，不覆盖任何文件。"""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env.dev"
content = (
    "DJANGO_SETTINGS_MODULE=personal_superagent.web.settings_dev\n"
    f"DJANGO_SECRET_KEY={secrets.token_hex(32)}\n"
    "PGDATABASE=personal_superagent\nPGUSER=personal_superagent\n"
    f"PGPASSWORD={secrets.token_hex(24)}\nPGHOST=127.0.0.1\nPGPORT=55432\n"
)
try:
    with target.open("x") as handle:
        target.chmod(0o600)
        handle.write(content)
    print("已生成 .env.dev（已忽略，不打印密钥）。")
except FileExistsError:
    print(".env.dev 已存在，未读取、未覆盖。")
