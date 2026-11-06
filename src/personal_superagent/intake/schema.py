from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated

Item = Annotated[str, Field(min_length=1, max_length=800)]


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=2500)
    materials: str = Field(default="", max_length=1500)
    deliverables: list[Item] = Field(min_length=1, max_length=12)
    acceptance: list[Item] = Field(min_length=1, max_length=12)
    questions: list[Item] = Field(default_factory=list, max_length=12)
    assumptions: list[Item] = Field(default_factory=list, max_length=12)
    device_needs: str = Field(default="无需本地工具", max_length=1000)

    def description(self):
        sections = [
            ("目标", self.goal),
            ("材料", self.materials),
            ("交付物", self.deliverables),
            ("验收标准", self.acceptance),
            ("用户接受的假设", self.assumptions),
            ("设备需求", self.device_needs),
        ]
        text = "\n\n".join(
            f"## {name}\n"
            + ("\n".join(f"- {x}" for x in value) if isinstance(value, list) else value)
            for name, value in sections
        )
        if len(text) > 10000:
            raise ValueError("草稿超长，请精简")
        return text
