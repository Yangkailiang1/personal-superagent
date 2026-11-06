"""新版本分流放在图目录外，不能改变 V0.4 目录哈希。"""
def module_for(version):
    if version=='0.6.0':
        from personal_superagent.workflow_v06 import checkpoints
        return checkpoints
    from personal_superagent.workflow.versions import module_for as old
    return old(version)
