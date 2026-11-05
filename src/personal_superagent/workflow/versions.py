"""保留 V0.3 原样图定义，避免升级使已等待审批的 checkpoint 失效。"""

from importlib import import_module


def module_for(version):
    if version == "0.3.0":
        return import_module("personal_superagent.workflow_v03.checkpoints")
    if version == "0.4.0":
        return import_module("personal_superagent.workflow.checkpoints")
    raise ValueError("执行版本不受支持；不能从头覆盖 checkpoint")
