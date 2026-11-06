"""在 Blender 内执行的固定程序。几何与材质参数来自已验证的 SceneSpec。"""

import json
import math
from pathlib import Path
import bpy
from mathutils import Vector


def apply_scene(payload, directory):
    spec = json.loads(payload)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    materials = {}
    for item in spec["materials"]:
        mat = bpy.data.materials.new(item["name"])
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (*item["color"], 1)
        bsdf.inputs["Roughness"].default_value = item["roughness"]
        bsdf.inputs["Metallic"].default_value = item["metallic"]
        if item["patch_color"]:
            noise = nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = item["noise_scale"]
            ramp = nodes.new("ShaderNodeValToRGB")
            t = item["patch_threshold"]
            ramp.color_ramp.elements[0].position = max(0.01, t - 0.12)
            ramp.color_ramp.elements[0].color = (*item["color"], 1)
            ramp.color_ramp.elements[1].position = min(0.99, t + 0.12)
            ramp.color_ramp.elements[1].color = (*item["patch_color"], 1)
            mat.node_tree.links.new(noise.outputs["Fac"], ramp.inputs[0])
            mat.node_tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.12
            bump.inputs["Distance"].default_value = 0.035
            mat.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            mat.node_tree.links.new(bump.outputs[0], bsdf.inputs["Normal"])
        materials[item["name"]] = mat
    for item in spec["objects"]:
        kind = item["type"]
        if kind == "sphere":
            bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20)
        elif kind == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1, depth=2)
        elif kind == "cone":
            bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=1, radius2=0, depth=2)
        elif kind == "torus":
            bpy.ops.mesh.primitive_torus_add(
                major_radius=1, minor_radius=item["radius"]
            )
        elif kind == "curve":
            curve = bpy.data.curves.new(item["name"], "CURVE")
            curve.dimensions = "3D"
            curve.bevel_depth = item["radius"]
            curve.bevel_resolution = 4
            spline = curve.splines.new("BEZIER")
            spline.bezier_points.add(len(item["points"]) - 1)
            for p, co in zip(spline.bezier_points, item["points"]):
                p.co = co
                p.handle_left_type = "AUTO"
                p.handle_right_type = "AUTO"
            obj = bpy.data.objects.new(item["name"], curve)
            bpy.context.collection.objects.link(obj)
            bpy.context.view_layer.objects.active = obj
        else:
            mesh = bpy.data.meshes.new(item["name"])
            mesh.from_pydata(item["points"], [], item["faces"])
            mesh.update()
            obj = bpy.data.objects.new(item["name"], mesh)
            bpy.context.collection.objects.link(obj)
            bpy.context.view_layer.objects.active = obj
        obj = bpy.context.view_layer.objects.active
        obj.name = item["name"]
        obj.location = item["location"]
        obj.scale = item["scale"]
        obj.rotation_euler = item["rotation"]
        obj.data.materials.append(materials[item["material"]])
        if obj.type == "MESH":
            for p in obj.data.polygons:
                p.use_smooth = True
            if item["subdivision"]:
                modifier = obj.modifiers.new("Surface", "SUBSURF")
                modifier.levels = item["subdivision"]
    bpy.ops.object.camera_add(location=spec["camera"])
    camera = bpy.context.object
    camera.rotation_euler = (
        (Vector(spec["target"]) - camera.location).to_track_quat("-Z", "Y").to_euler()
    )
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 9
    bpy.context.scene.camera = camera
    for location, power, size in [
        ((1, -4, 7), 1200, 5),
        ((-5, -1, 3), 800, 4),
        ((3, 4, 5), 1400, 3),
    ]:
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.data.energy = power
        light.data.shape = "DISK"
        light.data.size = size
        light.rotation_euler = (
            (Vector(spec["target"]) - light.location)
            .to_track_quat("-Z", "Y")
            .to_euler()
        )
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.world.color = (0.18, 0.18, 0.18)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(Path(directory) / "preview.png")
    scene["task_title"] = spec["title"]
    scene["model_object_count"] = len(spec["objects"])
    bpy.ops.wm.save_as_mainfile(
        filepath=str(Path(directory) / "model.blend"), check_existing=False
    )
    print(
        json.dumps(
            {
                "objects": len(spec["objects"]),
                "materials": len(materials),
                "saved": "model.blend",
            }
        )
    )


def inspect_scene():
    meshes = [o for o in bpy.context.scene.objects if o.type in {"MESH", "CURVE"}]
    print(
        json.dumps(
            {
                "objects": len(meshes),
                "names": [o.name for o in meshes],
                "materials": len(bpy.data.materials),
                "camera": bool(bpy.context.scene.camera),
            }
        )
    )
