import argparse
import uuid
from .config import directory, load, save, validate_url
from .files import TOOLS, describe_root
from .agent import request, run
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="个人 Superagent 本地客户端（macOS/Linux/WSL2）"
    )
    parser.add_argument("--config-dir")
    sub = parser.add_subparsers(dest="action", required=True)
    pair = sub.add_parser("pair")
    pair.add_argument("--url", required=True)
    pair.add_argument("--code", required=True)
    pair.add_argument("--name", required=True)
    grant = sub.add_parser("grant")
    grant.add_argument("--name", required=True)
    grant.add_argument("--path", required=True)
    grant.add_argument("--tools", default="list_files,read_text")
    grant.add_argument("--ack-cloud-transfer", action="store_true", required=True)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--name", required=True)
    start = sub.add_parser("run")
    start.add_argument("--once", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args()
    try:
        root = directory(args.config_dir)
        if args.action == "pair":
            if (root / "client.json").exists():
                raise ValueError("已有绑定配置，请使用独立配置目录，不覆盖原凭证")
            config = {"url": validate_url(args.url), "roots": []}
            config.update(
                request(config, "pair", {"code": args.code, "name": args.name})
            )
            save(root, config)
            print("设备绑定成功，凭证已安全保存，未输出 token。")
        elif args.action == "run":
            run(root, once=args.once)
        else:
            config = load(root)
            if args.action == "grant":
                tools = set(args.tools.split(","))
                if not tools <= TOOLS or not tools:
                    raise ValueError("工具只支持 list_files/read_text/write_text")
                if any(r["label"] == args.name for r in config["roots"]):
                    raise ValueError("名称已存在，请先 revoke 再重新授权")
                info = describe_root(args.path)
                if root.resolve().is_relative_to(Path(info["path"])):
                    raise ValueError("授权范围覆盖客户端凭证目录，请选择更小的资料目录")
                if len(config["roots"]) >= 16:
                    raise ValueError("最多授权 16 个目录")
                config["roots"].append(
                    {
                        "id": str(uuid.uuid4()),
                        "label": args.name,
                        "tools": sorted(tools),
                        **info,
                    }
                )
                save(root, config)
                print(
                    "目录授权已保存；运行客户端同步到云端。write_text 仅新建文件，不覆盖。"
                )
            elif args.action == "revoke":
                config["roots"] = [
                    r for r in config["roots"] if r["label"] != args.name
                ]
                save(root, config)
                print("本地授权已撤销，下一次轮询同步云端。")
            else:
                print("服务器：", config["url"])
                for item in config["roots"]:
                    print(item["label"], ",".join(item["tools"]))
    except (ValueError, OSError) as exc:
        raise SystemExit(
            "客户端未完成：" + str(exc)
            if isinstance(exc, ValueError)
            else "客户端文件或网络错误，请检查配置；凭证未输出。"
        ) from None


if __name__ == "__main__":
    main()
