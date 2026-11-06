"""独立 factory-startup Blender，只加载用户已安装的 addon；不启动其他插件。"""

import argparse
import importlib.util
import sys
import time

p = argparse.ArgumentParser()
p.add_argument("--addon")
p.add_argument("--port", type=int)
a = p.parse_args(sys.argv[sys.argv.index("--") + 1 :])
spec = importlib.util.spec_from_file_location("superagent_blender_addon", a.addon)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
if module.ADDON_PROTOCOL_VERSION != 15:
    raise RuntimeError("Blender addon protocol mismatch")
import bpy

if bpy.app.background:
    raise RuntimeError("Blender MCP requires a dedicated GUI process")
# 只注册已装插件的本地属性；关闭自动启动和更新网络检查。
module._blendermcp_register_auto_start = lambda: None
module._addon_update_check_on_startup = lambda: None
module.register()
for prop in bpy.context.scene.bl_rna.properties:
    if prop.identifier.startswith("blendermcp_use_") and prop.type == "BOOLEAN":
        setattr(bpy.context.scene, prop.identifier, False)
server = module.BlenderMCPServer(host="127.0.0.1", port=a.port)
server.start()
