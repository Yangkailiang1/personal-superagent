"""真实 Git worktree / 命令；不调用付费模型。"""

import subprocess
import uuid
from pathlib import Path
import pytest
from personal_superagent.client.happier.repositories import (
    register,
    prepare,
    collect,
    resolve_repository,
)
from personal_superagent.happier.policy import RepositoryPolicy


def git(repo, *args):
    return (
        subprocess.check_output(
            ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL
        )
        .decode()
        .strip()
    )


def test_worktree_preserves_dirty_original_and_collects_new_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    client = tmp_path / "client"
    client.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "base.txt").write_text("base")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    (repo / "base.txt").write_text("user uncommitted")
    (repo / "user.txt").write_text("private original")
    binding = register(
        client, "test", repo, ["result.txt"], ["python --version"], "HEAD"
    )
    job = {
        "id": str(uuid.uuid4()),
        "instance": str(uuid.uuid4()),
        "snapshot": {
            "repository_id": binding["id"],
            "base_commit": binding["baseline"],
            "policy": binding["policy"],
        },
    }
    path, branch = prepare(client, job)
    assert (path / "base.txt").read_text() == "base"
    assert not (path / "user.txt").exists()
    (path / "result.txt").write_text("agent output")
    report = collect(path, binding["policy"])
    assert report["files"] == [{"path": "result.txt", "content": "agent output"}]
    assert not report["violations"]
    (path / "base.txt").write_text("outside scope")
    report = collect(path, binding["policy"])
    assert "base.txt" in report["violations"]
    assert "outside scope" not in report["diff"]
    assert (repo / "base.txt").read_text() == "user uncommitted"
    assert (repo / "user.txt").read_text() == "private original"
    assert git(repo, "branch", "--show-current") != branch
    (path / "base.txt").unlink()
    deleted = collect(path, {"write_paths": ["."]})
    assert any(f["path"] == "base.txt" and f.get("deleted") for f in deleted["files"])
    assert "-base" in deleted["diff"]
    with pytest.raises(ValueError):
        prepare(client, job)


def test_scope_and_symlink_change_denied(tmp_path):
    for path in ["../outside", ".git/config", "/tmp/escape", ".env"]:
        with pytest.raises(ValueError):
            RepositoryPolicy(write_paths=[path])
    with pytest.raises(ValueError):
        RepositoryPolicy(write_paths=["src"], checks=["pytest; curl x"])


def test_upstream_sources_match_pinned_manifest():
    import hashlib
    import json

    upstream = Path(__file__).resolve().parents[1] / "executor/src/upstream"
    manifest = json.loads((upstream / "manifest.json").read_text())
    assert manifest["commit"] == "47de280241d02d8b338b4e62f39983679716b044"
    for item in manifest["files"]:
        name = item["path"].rsplit("/", 1)[-1]
        data = (
            upstream / (name + ".reference" if name.endswith(".ts") else name)
        ).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
    assert (upstream / "PushableAsyncIterable.ts").read_bytes() == (
        upstream / "PushableAsyncIterable.ts.reference"
    ).read_bytes()


def test_destructive_commands_cannot_be_registered_as_checks():
    with pytest.raises(ValueError):
        RepositoryPolicy(write_paths=["src"], checks=["rm -rf src"])
