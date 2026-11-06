"""受限 MCP facade → 已装 Blender addon socket；模型没有 execute_code 工具。"""

import json
import os
import socket
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .schema import SceneSpec

mcp = FastMCP("blender")


def rpc(kind, params=None):
    with socket.create_connection(
        ("127.0.0.1", int(os.environ["BLENDER_MCP_PORT"])), timeout=10
    ) as s:
        s.settimeout(240)
        s.sendall(json.dumps({"type": kind, "params": params or {}}).encode())
        data = b""
        while len(data) < 2000000:
            part = s.recv(65536)
            if not part:
                break
            data += part
            try:
                response = json.loads(data)
                break
            except ValueError:
                continue
        else:
            raise ValueError("Blender response too large")
    if response.get("status") != "success":
        raise ValueError("Blender operation failed")
    return response["result"]


def execute(code):
    return rpc("execute_code", {"code": code})


def directory():
    return Path(os.environ["BLENDER_OUTPUT_DIR"]).resolve()


@mcp.tool()
def build_model(spec: SceneSpec) -> dict:
    """Build an editable 3D scene from validated geometry/material parameters. Replaces only this task's isolated scene. Front faces -Y, up is Z. Saves model.blend locally. No Python input."""
    root = directory()
    (root / "scene_spec.json").write_text(spec.model_dump_json(indent=2))
    program = Path(__file__).with_name("scene_program.py").read_text()
    return execute(
        program
        + "\napply_scene("
        + repr(spec.model_dump_json())
        + ","
        + repr(str(root))
        + ")"
    )


@mcp.tool()
def inspect_model() -> dict:
    """Inspect current task objects, material and camera facts without exposing files."""
    program = Path(__file__).with_name("scene_program.py").read_text()
    return execute(program + "\ninspect_scene()")


@mcp.tool()
def render_model() -> dict:
    """Render preview.png and save the editable Blender file in this task's local directory. Does not upload images."""
    root = directory()
    return execute(
        "bpy.context.scene.render.filepath="
        + repr(str(root / "preview.png"))
        + "\nbpy.ops.render.render(write_still=True)\nbpy.ops.wm.save_as_mainfile(filepath="
        + repr(str(root / "model.blend"))
        + ',check_existing=False)\nprint("Local render and Blender file saved")'
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
