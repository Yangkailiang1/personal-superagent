"""云端验证公开授权；本机仍须用自己的授权重新校验，不能执行云端任意配置。"""

import re
import shlex
from pathlib import PurePosixPath
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RepositoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    write_paths: list[str] = Field(min_length=1, max_length=24)
    checks: list[str] = Field(default_factory=list, max_length=12)
    max_turns: int = Field(default=16, ge=1, le=24)
    timeout: int = Field(default=1800, ge=30, le=1800)

    @field_validator("write_paths")
    @classmethod
    def paths(cls, values):
        for value in values:
            p = PurePosixPath(value)
            if (
                not value
                or p.is_absolute()
                or ".." in p.parts
                or any(
                    x == ".git" or x.startswith(".env") or x.startswith(".server")
                    for x in p.parts
                )
                or "\\" in value
                or "\0" in value
            ):
                raise ValueError("写入范围必须为仓库相对路径")
        return sorted(set(values))

    @field_validator("checks")
    @classmethod
    def commands(cls, values):
        if any(
            not re.fullmatch(r"[a-zA-Z0-9_ ./=:-]{1,300}", v) or ".." in v
            for v in values
        ):
            raise ValueError("预授权检查只能为无 Shell 组合的完整命令")
        allowed = [
            ("python", "-m", "pytest"),
            ("python3", "-m", "pytest"),
            ("pytest",),
            ("npm", "test"),
            ("npm", "run", "test"),
            ("npm", "run", "build"),
            ("pnpm", "test"),
            ("pnpm", "run", "build"),
            ("git", "status", "--short"),
            ("python", "--version"),
            ("python3", "--version"),
        ]
        for command in values:
            argv = tuple(shlex.split(command))
            if not any(argv[: len(prefix)] == prefix for prefix in allowed):
                raise ValueError(
                    "本版预授权检查仅支持 Python/Node 测试构建及只读 Git/版本检查；其他命令逐次审批"
                )
        return values


def validate_manifest(item):
    import uuid

    uuid.UUID(item["id"])
    if not isinstance(item["label"], str) or not 1 <= len(item["label"]) <= 100:
        raise ValueError("仓库名称无效")
    if not re.fullmatch(r"[0-9a-f]{40}", item["baseline"]):
        raise ValueError("必须绑定完整提交")
    return RepositoryPolicy.model_validate(item["policy"]).model_dump()


def subset(paths, authorized):
    return all(
        any(a == "." or p == a or p.startswith(a.rstrip("/") + "/") for a in authorized)
        for p in paths
    )


class FileResult(BaseModel):
    deleted: bool = False
    path: str = Field(max_length=1000)
    content: str = Field(max_length=200000)


class CheckResult(BaseModel):
    command: str = Field(max_length=300)
    exit_code: int
    output: str = Field(default="", max_length=20000)


class Delivery(BaseModel):
    # 模型 usage 的字段由供应商定义；仅展示，不宣称精确控制账户账单。
    model_config = ConfigDict(extra="forbid")
    state: str = Field(pattern=r"^(succeeded|failed|cancelled|interrupted)$")
    text: str = Field(default="", max_length=100000)
    error: str = Field(default="", max_length=1000)
    files: list[FileResult] = Field(default_factory=list, max_length=1000)
    changed_paths: list[str] = Field(default_factory=list, max_length=2000)
    violations: list[str] = Field(default_factory=list, max_length=2000)
    checks: list[CheckResult] = Field(default_factory=list, max_length=12)
    diff: str = Field(default="", max_length=1000000)
    branch: str = Field(default="", max_length=200)
    session_id: str = Field(default="", max_length=160)
    usage: dict = Field(default_factory=dict)
    cost_usd: float | None = None
    independent_verification: bool = False
