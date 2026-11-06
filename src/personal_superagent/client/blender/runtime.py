"""独立 Blender + 固定 MCP facade + 本机 Claude；原始产物从不上传。"""

import hashlib, json, mimetypes, os, queue, socket, subprocess, sys, threading, time, uuid
from pathlib import Path
from personal_superagent.client.agent import request
from personal_superagent.client.config import load
from personal_superagent.client.happier.ledger import Ledger
from personal_superagent.client.happier.worker import EXECUTOR, stop
from personal_superagent.client.happier.provider import info
from .mcp_server import rpc

BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
ADDON = (
    Path.home()
    / "Library/Application Support/Blender/5.2/scripts/addons/blender-addon.py"
)


def config(root):
    return json.loads((root / "blender.json").read_text())


def register(root, output):
    provider = info(EXECUTOR)
    checked = root / "provider-check.json"
    if (
        not checked.exists()
        or json.loads(checked.read_text())["fingerprint"] != provider["fingerprint"]
    ):
        raise ValueError("先运行 happier-check --live 验证本机真实工具调用")
    if not BLENDER.exists() or not ADDON.exists():
        raise ValueError("未找到 Blender 或已安装 addon")
    path = Path(output).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if root.resolve().is_relative_to(path) or path.is_relative_to(root.resolve()):
        raise ValueError("输出目录不能包含客户端凭据")
    cfg = {
        "output": str(path),
        "grant_id": str(uuid.uuid4()),
        "provider_fingerprint": provider["fingerprint"],
        "model": provider["model"],
        "addon_hash": hashlib.sha256(ADDON.read_bytes()).hexdigest(),
        "protocol": 15,
    }
    fd = os.open(root / "blender.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f)
    return cfg


def manifest(root):
    cfg = config(root)
    if hashlib.sha256(ADDON.read_bytes()).hexdigest() != cfg["addon_hash"]:
        raise ValueError("Blender 插件已变化，请重新检查并授权")
    return {k: v for k, v in cfg.items() if k != "output"}


def call(config, job, action, **data):
    return request(
        config,
        "modeling-control",
        {
            "id": job["id"],
            "token": job["token"],
            "instance": job["instance"],
            "action": action,
            **data,
        },
    )


def metadata(directory):
    files = []
    for name in ["model.blend", "preview.png", "scene_spec.json"]:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("本机交付缺失")
        files.append(
            {
                "path": name,
                "media_type": mimetypes.guess_type(name)[0] or "application/x-blender",
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return files


def execute(root, connection, db, job):
    cfg = config(root)
    if (
        manifest(root) != job["snapshot"]["capability"]
        or info(EXECUTOR)["fingerprint"] != cfg["provider_fingerprint"]
    ):
        raise ValueError("本机能力或模型配置改变")
    id = str(uuid.UUID(job["id"]))
    instance = str(uuid.UUID(job["instance"]))
    directory = Path(cfg["output"]) / id
    if directory.exists():
        raise ValueError("已存在工作区，不重复执行")
    db.begin(job)
    directory.mkdir(mode=0o700)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT"}
    }
    env["WORKBENCH_RUN_INSTANCE"] = instance
    blender = None
    agent = None
    events = queue.Queue()
    sequence = 0
    result = {"state": "interrupted", "error": "本机建模未完成"}
    try:
        log = (directory / "blender.log").open("w")
        blender = subprocess.Popen(
            [
                str(BLENDER),
                "--factory-startup",
                "--disable-autoexec",
                "--python",
                str(Path(__file__).with_name("bootstrap.py")),
                "--",
                "--addon",
                str(ADDON),
                "--port",
                str(port),
            ],
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,
        )
        import psutil

        db.process(id, blender.pid, psutil.Process(blender.pid).create_time())
        os.environ["BLENDER_MCP_PORT"] = str(port)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not call(connection, job, "heartbeat")["continue"]:
                raise ValueError("归属失效")
            try:
                if rpc("ping")["pong"]:
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise ValueError("Blender MCP 未启动")
        secret_names = [
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
        ]
        mcp = {
            "blender": {
                "command": sys.executable,
                "args": ["-m", "personal_superagent.client.blender.mcp_server"],
                "env": {
                    **{k: "" for k in secret_names},
                    "BLENDER_MCP_PORT": str(port),
                    "BLENDER_OUTPUT_DIR": str(directory),
                },
            }
        }
        agent = subprocess.Popen(
            ["node", str(EXECUTOR), instance],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
            start_new_session=True,
        )
        db.process(id, agent.pid, psutil.Process(agent.pid).create_time())
        # 两个进程身份均持久化，重启时不能只确认 Node 已停而遗漏 Blender。
        (directory / "processes.json").write_text(
            json.dumps(
                [
                    {
                        "pid": p.pid,
                        "birth": psutil.Process(p.pid).create_time(),
                        "instance": instance,
                    }
                    for p in [blender, agent]
                ]
            )
        )
        prompt = (
            job["snapshot"]["description"]
            + "\n云端研究交付："
            + json.dumps(job["snapshot"]["context"], ensure_ascii=False)
            + "\n你是本机 Blender 建模 Agent。根据研究证据独立设计模型，不预设奶白色卡通。必须使用 blender MCP 的 build_model、inspect_model、render_model 完成建模和实际渲染。你可以改进场景后重新渲染。前方为 -Y，上方为 Z。主体放在原点附近，合理设置 camera/target，整体宽度不超过 6。通过对象命名表达解剖部位与材质，曲线用点集和圆管半径塑造四肢/脚趾。可用噪声斑纹材质。最终简短说明选择的造型、完成内容与局限，文件只留本机，不上传图片或文件字节。"
        )
        agent.stdin.write(
            json.dumps(
                {
                    "protocol": 1,
                    "action": "start",
                    "cwd": str(directory),
                    "blender": True,
                    "provider_fingerprint": cfg["provider_fingerprint"],
                    "local_mcp": mcp,
                    "prompt": prompt,
                    "write_paths": [],
                    "checks": [],
                    "max_turns": job["snapshot"]["policy"]["max_turns"],
                }
            )
            + "\n"
        )
        agent.stdin.flush()

        def read():
            for line in agent.stdout:
                try:
                    events.put(json.loads(line))
                except ValueError:
                    events.put({"kind": "error"})
            events.put(None)

        threading.Thread(target=read, daemon=True).start()
        start = time.monotonic()
        last = 0
        terminal = None
        tool_success = set()
        while time.monotonic() - start < job["snapshot"]["policy"]["timeout"]:
            if time.monotonic() - last > 3:
                if (
                    manifest(root) != job["snapshot"]["capability"]
                    or not call(connection, job, "heartbeat")["continue"]
                ):
                    raise ValueError("授权或归属改变")
                last = time.monotonic()
            try:
                e = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if e is None:
                break
            db.event(id, e)
            if e["kind"] == "result":
                terminal = e
                break
            if e["kind"] == "tool_start":
                tool_success.add(e["tool"])
                # 三维参数/本机路径只留本机账本；云端只收活动摘要。
                event = {
                    "kind": "tool_start",
                    "tool": e["tool"],
                    "call_id": e.get("call_id"),
                    "args": {"detail": "本机建模参数不上传"},
                }
            elif e["kind"] in {"tool_end", "session"}:
                event = e
            else:
                continue
            sequence += 1
            call(connection, job, "event", sequence=sequence, event=event)
        stop(agent)
        if (
            not terminal
            or terminal["state"] != "succeeded"
            or not any(t.endswith("render_model") for t in tool_success)
        ):
            raise ValueError("没有完整模型执行结果")
        rpc("execute_code", {"code": 'print("scene finalized")'})
        stop(blender)
        # 独立重开文件并检查，不以模型口头声明代替验证。
        verify = subprocess.run(
            [
                str(BLENDER),
                "--background",
                "--factory-startup",
                "--disable-autoexec",
                str(directory / "model.blend"),
                "--python-expr",
                'import bpy,json; assert len([o for o in bpy.context.scene.objects if o.type in {"MESH","CURVE"}])>0; assert bpy.context.scene.camera; print("MODEL_REOPEN_OK")',
            ],
            capture_output=True,
            timeout=45,
            env=env,
        )
        if verify.returncode or b"MODEL_REOPEN_OK" not in verify.stdout:
            raise ValueError("模型重开检查失败")
        from PIL import Image

        with Image.open(directory / "preview.png") as image:
            image.verify()
        result = {
            "state": "succeeded",
            "text": terminal.get("text", "").replace(str(directory), "[本机交付目录]")[
                :3000
            ],
            "local_files": metadata(directory),
            "checks": [],
            "files": [],
            "violations": [],
        }
    except (ValueError, OSError, subprocess.SubprocessError, KeyError):
        result = {
            "state": "interrupted",
            "error": "本机建模/检查未完成，现场已保留，不自动重放",
        }
    finally:
        if agent:
            stop(agent)
        if blender:
            stop(blender)
        db.finish(id, result)
    call(connection, job, "result", report=result)
    db.ack(id)


def sync_files(root, connection):
    cfg = config(root)
    index = root / "modeling-files.json"
    known = json.loads(index.read_text()) if index.exists() else []
    statuses = []
    for file in known:
        path = Path(cfg["output"]) / str(uuid.UUID(file["attempt_id"])) / file["path"]
        state = (
            "missing"
            if not path.is_file()
            else "available"
            if hashlib.sha256(path.read_bytes()).hexdigest() == file["sha256"]
            else "changed"
        )
        statuses.append({"id": file["id"], "state": state})
    data = request(connection, "modeling-files", {"files": statuses, "opened": []})
    opened = []
    open_ledger = root / "modeling-opened.json"
    seen = set(json.loads(open_ledger.read_text())) if open_ledger.exists() else set()
    for f in data["open"]:
        if f["open_request_id"] not in seen:
            path = Path(cfg["output"]) / str(uuid.UUID(f["attempt_id"])) / f["path"]
            if (
                path.is_file()
                and not path.is_symlink()
                and path.resolve().is_relative_to(Path(cfg["output"]).resolve())
                and hashlib.sha256(path.read_bytes()).hexdigest() == f["sha256"]
            ):
                seen.add(f["open_request_id"])
                open_ledger.write_text(json.dumps(list(seen)))
                if path.suffix == ".blend":
                    subprocess.Popen(
                        [str(BLENDER), "--disable-autoexec", str(path)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                elif path.suffix in {".png", ".json"}:
                    subprocess.Popen(["open", str(path)])
        opened.append(f["open_request_id"])
    request(connection, "modeling-files", {"files": statuses, "opened": opened})
    index.write_text(json.dumps(data["files"]))


def reconcile(root, connection, db):
    # 未完成账本不可当作从未执行；保留并阻止自动重派。
    for id, payload, pid, birth, result in db.unfinished():
        job = json.loads(payload)
        if result is None:
            import psutil

            directory = Path(config(root)["output"]) / str(uuid.UUID(id))
            path = directory / "processes.json"
            identities = (
                json.loads(path.read_text())
                if path.exists()
                else ([{"pid": pid, "birth": birth}] if pid else [])
            )
            for identity in identities:
                if (
                    psutil.pid_exists(identity["pid"])
                    and abs(
                        psutil.Process(identity["pid"]).create_time()
                        - identity["birth"]
                    )
                    < 0.01
                ):
                    raise ValueError(
                        "旧建模进程尚未确认停止；请先在本机核查，不自动重派"
                    )
            result = json.dumps(
                {
                    "state": "interrupted",
                    "error": "本机确认旧进程均已停止，未重放；请显式重试",
                }
            )
            db.finish(id, json.loads(result))
        call(connection, job, "result", report=json.loads(result))
        db.ack(id)


def run(root, once=False):
    connection = load(root)
    db = Ledger(root)
    try:
        while True:
            try:
                reconcile(root, connection, db)
                request(connection, "modeling-hello", {"config": manifest(root)})
                sync_files(root, connection)
                job = request(connection, "modeling-claim", {})["job"]
                if job:
                    execute(root, connection, db, job)
                if once:
                    return
            except OSError as exc:
                from urllib.error import HTTPError

                if isinstance(exc, HTTPError) and exc.code in {400, 401, 403, 404, 409}:
                    raise ValueError(
                        "设备凭证、协议或执行归属已失效，请检查本机记录"
                    ) from None
                if once:
                    raise
                # 只重连控制面和补传回执，绝不把中断执行当成新任务启动。
                time.sleep(3)
                continue
            time.sleep(2)
    finally:
        db.db.close()
