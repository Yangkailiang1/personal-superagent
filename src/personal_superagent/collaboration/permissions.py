"""共享发布权限校验，不能用提示词代替资源匹配。"""


def check_scope(attempt, agent):
    scope = attempt.input_snapshot.get("device")
    if scope and (
        not agent.grant
        or agent.grant.revision != scope["revision"]
        or not set(scope["tools"]) <= set(agent.grant.tools)
    ):
        return False
    return attempt.input_snapshot["workflow"] == agent.model_config.get(attempt.mode)
