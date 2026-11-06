import pytest
from personal_superagent.client.blender.schema import SceneSpec
from personal_superagent.client.happier.provider import info
from personal_superagent.client.happier.worker import EXECUTOR


def test_scene_validation_no_python_or_invalid_paths():
    scene = {
        "title": "shape",
        "materials": [{"name": "surface", "color": [0.1, 0.2, 0.3]}],
        "objects": [{"name": "shape", "material": "surface"}],
    }
    assert SceneSpec.model_validate(scene).objects[0].type == "sphere"
    with pytest.raises(ValueError):
        SceneSpec.model_validate({**scene, "code": "import os"})
    with pytest.raises(ValueError):
        SceneSpec.model_validate(
            {**scene, "objects": [{"name": "bad", "material": "missing"}]}
        )
    with pytest.raises(ValueError):
        SceneSpec.model_validate(
            {
                **scene,
                "objects": [
                    {"name": "bad", "material": "surface", "scale": [-1, 1, 1]}
                ],
            }
        )


def test_native_research_delegation_caps_parallel_search_without_failing():
    import json, io, os
    from unittest.mock import patch
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatResult, ChatGeneration
    from personal_superagent.modeling.research import run_research

    class Model(BaseChatModel):
        count: int = 0

        @property
        def _llm_type(self):
            return "fixed-research-test"

        def bind_tools(self, *args, **kwargs):
            return self

        def _generate(self, messages, **kwargs):
            index = self.count
            self.count += 1
            if index == 0:
                m = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "delegate",
                            "name": "task",
                            "args": {
                                "subagent_type": "researcher",
                                "description": "Look up the subject using the authorized tool",
                            },
                        }
                    ],
                )
            elif index == 1:
                m = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "s" + str(i),
                            "name": "search_web",
                            "args": {"query": "subject " + str(i)},
                        }
                        for i in range(4)
                    ],
                )
            else:
                m = AIMessage(
                    content="Research summary with evidence https://example.invalid/evidence"
                )
            return ChatResult(generations=[ChatGeneration(message=m)])

    def response(*args, **kwargs):
        return io.BytesIO(
            json.dumps(
                {
                    "results": [
                        {
                            "title": "Evidence",
                            "url": "https://example.invalid/evidence",
                            "content": "Reference material",
                        }
                    ]
                }
            ).encode()
        )

    events = []
    with (
        patch("personal_superagent.models.build_model", return_value=Model()),
        patch("urllib.request.urlopen", side_effect=response) as http,
        patch.dict(os.environ, {"TAVILY_API_KEY": "test-only"}),
    ):
        result = json.loads(
            run_research(
                {"description": "test delegation", "max_calls": 8},
                lambda k, d: events.append((k, d)),
            )
        )
    assert http.call_count == 3
    assert result["counts"]["delegations"] == 1
    assert result["counts"]["searches"] == 3
    assert any(k == "subagent_end" and d["state"] == "completed" for k, d in events)


def test_blender_applies_radius_before_object_scale(tmp_path):
    """真实 Blender 回归：防止小眼球/关节被错误建为半径 1 的大球。"""
    import subprocess, json
    from pathlib import Path

    blender = Path("/Applications/Blender.app/Contents/MacOS/Blender")
    if not blender.exists():
        pytest.skip("需要真实 Blender")
    import personal_superagent.client.blender as blender_package

    program = Path(blender_package.__file__).with_name("scene_program.py")
    spec = SceneSpec.model_validate(
        {
            "title": "geometry regression",
            "materials": [{"name": "surface", "color": [0.1, 0.2, 0.3]}],
            "objects": [
                {
                    "name": "radius-probe",
                    "material": "surface",
                    "radius": 0.25,
                    "scale": [2, 3, 4],
                }
            ],
        }
    ).model_dump_json()
    code = (
        program.read_text()
        + "\napply_scene("
        + repr(spec)
        + ","
        + repr(str(tmp_path))
        + ')\nbpy.context.view_layer.update()\nd=bpy.data.objects["radius-probe"].dimensions\nassert all(abs(a-b)<.01 for a,b in zip(d,[1,1.5,2])),list(d)\nprint("RADIUS_SCALE_OK")'
    )
    script = tmp_path / "check.py"
    script.write_text(code)
    result = subprocess.run(
        [
            str(blender),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python",
            str(script),
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0 and b"RADIUS_SCALE_OK" in result.stdout
