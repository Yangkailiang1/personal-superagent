"""命令行入口：输出图中的消息，观察一次工具调用循环。"""

import argparse

from langchain_core.messages import AIMessage, ToolMessage

from personal_superagent.agent import build_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="第一课：最小 DeepAgents")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--demo", action="store_true", help="离线固定示例，无网络模型调用")
    modes.add_argument("--real", action="store_true", help="真实模型调用，会产生供应商费用")
    parser.add_argument("--prompt", default="请调用工具计算 17 + 25。")
    args = parser.parse_args()
    if args.demo:
        print("离线模式：固定计算 17 + 25，不解释自定义 prompt。")
    try:
        graph = build_agent(demo=args.demo)
        result = graph.invoke(
            {"messages": [{"role": "user", "content": args.prompt}]},
            config={"recursion_limit": 12},
        )
    except Exception as exc:
        # 不打印供应商原始异常，避免请求地址或响应中夹带配置秘密。
        raise SystemExit(
            f"执行失败（{type(exc).__name__}）。请检查模式、模型配置、网络及工具调用支持。"
        ) from None
    for message in result["messages"]:
        if isinstance(message, AIMessage) and message.tool_calls:
            for call in message.tool_calls:
                print(f"[模型请求工具] {call['name']} {call['args']}")
        elif isinstance(message, ToolMessage):
            print(f"[工具返回] {message.content}")
        elif isinstance(message, AIMessage):
            print(f"[最终回答] {message.content}")


if __name__ == "__main__":
    main()
