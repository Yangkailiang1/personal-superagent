from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from personal_superagent.intake.schema import Draft, Item


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=800)
    options: list[Item] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.options)) != 3:
            raise ValueError("三个候选项必须不同")
        return self


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=2500)
    role: Literal["writer", "reviewer", "researcher", "image_designer", "coder", "modeler"] = "writer"
    required_capabilities: list[Literal["blender.modeling"]] = Field(default_factory=list,max_length=1)
    repository_id: str = ""
    repository_version: int = 0
    base_commit: str = ""
    write_paths: list[str] = Field(default_factory=list, max_length=24)
    checks: list[str] = Field(default_factory=list, max_length=12)
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    tools: list[str] = Field(default_factory=list, max_length=12)
    agent_id: str = ""
    grant_id: str = ""
    source_path: str = Field(default="input.md", max_length=200)
    deliverables: list[Item] = Field(min_length=1, max_length=12)
    acceptance: list[Item] = Field(min_length=1, max_length=12)


class Plan(Draft):
    steps: list[Step] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def acyclic(self):
        keys = {s.key for s in self.steps}
        if len(keys) != len(self.steps):
            raise ValueError("任务编号重复")
        done = set()
        for _ in self.steps:
            for step in self.steps:
                if not set(step.depends_on) <= keys:
                    raise ValueError("依赖不存在")
                if set(step.depends_on) <= done:
                    done.add(step.key)
        if done != keys:
            raise ValueError("任务依赖有环")
        return self


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["demo", "real"] = "demo"
    max_model_calls: int = Field(default=24, ge=1, le=48)
    max_images: int = Field(default=0, ge=0, le=2)
    timeout: int = Field(default=1800, ge=30, le=1800)
