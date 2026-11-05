"""工具边界：模型提出参数，Python 负责校验和计算。"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class AddInput(BaseModel):
    a: int = Field(strict=True, ge=-1_000_000, le=1_000_000)
    b: int = Field(strict=True, ge=-1_000_000, le=1_000_000)

class MultiplyInput(AddInput):
    """乘法输入；与加法输入相同。"""
    a:int = Field(strict=True, ge=-1_000_000, le=1_000_000)
    b:int = Field(strict=True, ge=-1_000_000, le=1_000_000)

@tool(args_schema=AddInput)
def add_numbers(a: int, b: int) -> str:
    """计算两个整数之和；每个整数必须在正负一百万以内。"""
    return str(a + b)

    
@tool(args_schema=MultiplyInput)
def multiply_numbers(a: int, b: int) -> str:
    """计算两个整数之积；每个整数必须在正负一百万以内。"""
    return str(a * b)