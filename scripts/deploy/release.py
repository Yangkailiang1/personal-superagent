"""发布已提交的代码包；不上传 .env/.server/数据，不自动回滚数据库。"""

import hashlib
import shlex
import subprocess
import tempfile
import tarfile
import gzip
from pathlib import Path

from remote import ROOT, connect, run

revision = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
).strip()
if subprocess.check_output(
    ["git", "status", "--porcelain", "--", "frontend"], cwd=ROOT
).strip():
    raise SystemExit("前端存在未提交修改，拒绝把它混入已提交版本发布")
# 在开发电脑构建，云服务器不用安装 Node。只将静态产物附加到已提交源码归档。
subprocess.run(
    ["npm", "ci", "--prefix", str(ROOT / "frontend")],
    check=True,
    stdout=subprocess.DEVNULL,
)
subprocess.run(
    ["npm", "run", "build", "--prefix", str(ROOT / "frontend")],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
for asset in (ROOT / "frontend" / "dist" / "assets").iterdir():
    if asset.suffix in {".js", ".css"}:
        asset.with_name(asset.name + ".gz").write_bytes(
            gzip.compress(asset.read_bytes(), compresslevel=9, mtime=0)
        )
with tempfile.TemporaryDirectory() as temporary:
    archive = Path(temporary) / "release.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), revision],
        cwd=ROOT,
        check=True,
    )
    with tarfile.open(archive, "a") as package:
        package.add(ROOT / "frontend" / "dist", arcname="frontend/dist")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    remote_archive = f"/tmp/personal-superagent-{revision}.tar"
    with connect() as client:
        with client.open_sftp() as sftp:
            sftp.put(str(archive), remote_archive)
            script_path = f"/tmp/personal-superagent-release-{revision}.sh"
            sftp.put(str(Path(__file__).parent / "release.sh"), script_path)
            sftp.chmod(script_path, 0o600)
        # 不经 bash stdin 传脚本：docker compose exec 会读取 stdin，可能吞掉后续脚本。
        result = run(
            client,
            f"bash {shlex.quote(script_path)} {shlex.quote(revision)} {shlex.quote(digest)} </dev/null",
        )
        raise SystemExit(result)
