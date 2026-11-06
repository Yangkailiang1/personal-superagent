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
