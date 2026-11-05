"""发布已提交的代码包；不上传 .env/.server/数据，不自动回滚数据库。"""
import hashlib
import shlex
import subprocess
import tempfile
from pathlib import Path

from remote import ROOT, connect, run

revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
with tempfile.TemporaryDirectory() as temporary:
    archive = Path(temporary) / "release.tar"
    subprocess.run(["git", "archive", "--format=tar", "-o", str(archive), revision], cwd=ROOT, check=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    remote_archive = f"/tmp/personal-superagent-{revision}.tar"
    with connect() as client:
        with client.open_sftp() as sftp:
            sftp.put(str(archive), remote_archive)
        script = (Path(__file__).parent / "release.sh").read_text()
        result = run(client, f"bash -se -- {shlex.quote(revision)} {shlex.quote(digest)}", script)
        raise SystemExit(result)
