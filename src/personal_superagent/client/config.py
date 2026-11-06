import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("服务器地址不能包含凭证、查询或片段")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError("必须使用 HTTPS，或通过本机 SSH 隧道访问 HTTP")
    return url.rstrip("/")


def directory(path=None) -> Path:
    root = Path(path or Path.home() / ".personal-superagent").expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def load(root: Path) -> dict:
    return json.loads((root / "client.json").read_text())


def save(root: Path, config: dict):
    # 供受限工具读取的目录授权快照，不含 token；撤销时先更新它。
    grants = root / "grants.next"
    fd = os.open(grants, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(config.get("roots", []), f)
    grants.replace(root / "grants.json")
    temporary = root / "client.next"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(config, handle, ensure_ascii=False)
    temporary.replace(root / "client.json")
    os.chmod(root / "client.json", 0o600)
