"""模型只决定结构化场景，不接收或执行模型生成的宿主 Python。"""

from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[float, Field(ge=-30, le=30, allow_inf_nan=False)]
Color = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Vector = Annotated[list[Number], Field(min_length=3, max_length=3)]
RGB = Annotated[list[Color], Field(min_length=3, max_length=3)]


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    color: RGB
    roughness: float = Field(default=0.4, ge=0, le=1)
    metallic: float = Field(default=0, ge=0, le=1)
    patch_color: RGB | None = None
    noise_scale: float = Field(default=4, ge=0.1, le=100)
    patch_threshold: float = Field(default=0.5, ge=0.05, le=0.95)


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    type: Literal["sphere", "cylinder", "cone", "torus", "curve", "mesh"] = "sphere"
    location: Vector = Field(default_factory=lambda: [0, 0, 0])
    scale: Vector = Field(default_factory=lambda: [1, 1, 1])
    rotation: Vector = Field(
        default_factory=lambda: [0, 0, 0], description="Euler radians"
    )
    material: str
    points: list[Vector] = Field(default_factory=list, max_length=5000)
    faces: list[list[int]] = Field(default_factory=list, max_length=5000)
    radius: float = Field(default=0.06, ge=0.005, le=5)
    subdivision: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def valid(self):
        if any(x <= 0 for x in self.scale):
            raise ValueError("缩放必须为正")
        if self.type == "curve" and len(self.points) < 2:
            raise ValueError("曲线至少两个点")
        if self.type == "mesh" and (
            not self.points
            or any(
                len(f) < 3
                or len(f) > 12
                or any(i < 0 or i >= len(self.points) for i in f)
                for f in self.faces
            )
        ):
            raise ValueError("网格索引无效")
        return self


class SceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    materials: list[Material] = Field(min_length=1, max_length=24)
    objects: list[Shape] = Field(min_length=1, max_length=180)
    camera: Vector = Field(default_factory=lambda: [6, -9, 5])
    target: Vector = Field(default_factory=lambda: [0, 0, 1])

    @model_validator(mode="after")
    def references(self):
        names = {m.name for m in self.materials}
        if len(names) != len(self.materials) or len(
            {o.name for o in self.objects}
        ) != len(self.objects):
            raise ValueError("名称重复")
        if any(o.material not in names for o in self.objects):
            raise ValueError("材质不存在")
        if sum(len(o.points) for o in self.objects) > 12000:
            raise ValueError("场景过大")
        return self
