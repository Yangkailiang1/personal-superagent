"""本机仓库授权：绝对路径只写本地 0600 文件；Git 操作关闭 hooks 和外部 diff。"""

import json
import os
import subprocess
import uuid
from pathlib import Path
from personal_superagent.happier.policy import RepositoryPolicy


def git(path, *args, timeout=30):
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "SYSTEMROOT", "TMPDIR"}
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0"
    )
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.pager=cat",
            "-C",
            str(path),
            *args,
        ],
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    if result.returncode:
        raise ValueError("Git 操作失败，请在本机检查仓库和基线；未修改原工作目录")
    return result.stdout.decode("utf-8", errors="replace")


def load(root):
    path = root / "repositories.json"
    return json.loads(path.read_text()) if path.exists() else []


def register(root, name, path, scopes, checks, base):
    original = Path(path).expanduser().absolute()
    if original.is_symlink():
        raise ValueError("仓库不能是符号链接")
    path = original.resolve(strict=True)
    if (
        path == root.resolve()
        or path.is_relative_to(root.resolve())
        or root.resolve().is_relative_to(path)
    ):
        raise ValueError("仓库不能覆盖客户端凭证目录")
    if Path(git(path, "rev-parse", "--show-toplevel").strip()).resolve() != path:
        raise ValueError("请选择仓库根目录")
    baseline = git(path, "rev-parse", "--verify", base + "^{commit}").strip()
    if len(baseline) != 40:
        raise ValueError("只支持 SHA-1 Git 仓库")
    policy = RepositoryPolicy(write_paths=scopes, checks=checks).model_dump()
    repos = load(root)
    if any(r["label"] == name for r in repos):
        raise ValueError("授权名已存在，请先撤销")
    if len(repos) >= 16:
        raise ValueError("最多授权 16 个仓库")
    record = {
        "id": str(uuid.uuid4()),
        "label": name,
        "path": str(path),
        "baseline": baseline,
        "policy": policy,
        "identity": [path.stat().st_dev, path.stat().st_ino],
    }
    repos.append(record)
    save(root, repos)
    return record


def save(root, repos):
    path = root / "repositories.next"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(repos, f, ensure_ascii=False)
    path.replace(root / "repositories.json")


def manifest(root):
    return [
        {k: r[k] for k in ("id", "label", "baseline", "policy")} for r in load(root)
    ]


def resolve_repository(root, snapshot):
    from personal_superagent.happier.policy import subset

    repo = next((r for r in load(root) if r["id"] == snapshot["repository_id"]), None)
    if not repo or repo["baseline"] != snapshot["base_commit"]:
        raise ValueError("本机仓库基线不匹配")
    path = Path(repo["path"])
    if (
        path.is_symlink()
        or list((path.stat().st_dev, path.stat().st_ino)) != repo["identity"]
    ):
        raise ValueError("仓库路径已被替换")
    policy = snapshot["policy"]
    if (
        not subset(policy["write_paths"], repo["policy"]["write_paths"])
        or not set(policy["checks"]) <= set(repo["policy"]["checks"])
        or policy["max_turns"] > repo["policy"]["max_turns"]
        or policy["timeout"] > repo["policy"]["timeout"]
    ):
        raise ValueError("任务超出本机授权")
    return repo


def prepare(root, job):
    # 任务标识只能是 UUID，云端不能用路径片段指定本机工作区。
    for key in ("id", "instance"):
        uuid.UUID(job[key])
    if job.get("task_id"):
        uuid.UUID(job["task_id"])
    repo = resolve_repository(root, job["snapshot"])
    path = root / "worktrees" / job["id"]
    path.parent.mkdir(mode=0o700, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(
        root.resolve()
    ):
        raise ValueError("工作区根目录已被替换")
    if path.exists():
        raise ValueError("已有工作区，不能重复启动，请核查本机账本")
    branch = f"codex/task/{job.get('task_id', job['id'])}/{job['id']}"
    git(repo["path"], "worktree", "add", "-b", branch, str(path), repo["baseline"])
    return path, branch


def collect(path, policy):
    """包含未跟踪文件；不执行仓库 diff driver/textconv，不跟随符号链接读文件。"""
    from personal_superagent.happier.policy import subset

    files = git(
        path, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "HEAD"
    ).split("\0")
    files += git(path, "ls-files", "--others", "-z").split("\0")
    files = sorted(set(f for f in files if f))
    violations = []
    texts = []
    size = 0
    for name in files:
        p = path / name
        if (
            not subset([name], policy["write_paths"])
            or any(
                x in {".git", ".env", ".server"} or x.startswith(".env.")
                for x in Path(name).parts
            )
            or p.is_symlink()
            or not p.resolve().is_relative_to(path.resolve())
        ):
            violations.append(name)
            continue
        if not p.exists():
            texts.append({"path": name, "content": "", "deleted": True})
            continue
        if not p.is_file():
            violations.append(name + "（不是普通文件）")
            continue
        if p.is_file():
            if p.stat().st_size > 200000:
                violations.append(name + "（单文件过大）")
                continue
            data = p.read_bytes()
            size += len(data)
            if b"\0" in data or size > 1000000:
                violations.append(name + "（二进制或总大小超限）")
                continue
            texts.append(
                {"path": name, "content": data.decode("utf-8", errors="replace")}
            )
    diff = (
        git(
            path,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "HEAD",
            "--",
            *[t["path"] for t in texts],
        )
        if texts
        else ""
    )
    if len(diff) > 1000000:
        violations.append("差异超过 1 MB")
        diff = diff[:1000000]
    return {
        "files": texts,
        "changed_paths": files,
        "violations": violations,
        "diff": diff,
        "independent_verification": False,
    }
