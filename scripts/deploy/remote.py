"""SSH 凭证只读本机 .server；固定主机指纹；不打印密码、不上传本地配置。"""
import argparse
import base64
import hashlib
import re
import select
import socketserver
import sys
from contextlib import contextmanager
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
FINGERPRINT = "KNfr7bRlSXwql2Y31fDBAr8hE6ZfTz1nxfNbMI8FfQA"


class PinnedHost(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        actual = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if actual != FINGERPRINT:
            raise paramiko.SSHException("SSH 主机指纹不匹配，已拒绝连接")


@contextmanager
def connect():
    values = {}
    for line in (ROOT / ".server").read_text().splitlines():
        match = re.match(r"^\s*([\w]+)\s*[:=：]\s*(.*?)\s*$", line)
        if match:
            values[match[1].lower()] = match[2].strip().strip("\"'")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(PinnedHost())
    try:
        client.connect(values["server_ip"], username=values["user"], password=values["password"],
                       port=int(values.get("port", "22")), timeout=20, allow_agent=False, look_for_keys=False)
        yield client
    finally:
        client.close()


def run(client, command, data=None):
    stdin, stdout, stderr = client.exec_command(command)
    if data is not None:
        stdin.write(data)
        stdin.flush()
    stdin.channel.shutdown_write()
    channel = stdout.channel
    while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
        if channel.recv_ready():
            sys.stdout.write(channel.recv(8192).decode(errors="replace")); sys.stdout.flush()
        if channel.recv_stderr_ready():
            sys.stderr.write(channel.recv_stderr(8192).decode(errors="replace")); sys.stderr.flush()
        select.select([channel], [], [], 0.2)
    return channel.recv_exit_status()


def tunnel(client, port):
    transport = client.get_transport()
    class Forward(socketserver.BaseRequestHandler):
        def handle(self):
            channel = transport.open_channel("direct-tcpip", ("127.0.0.1", 8000), self.request.getpeername())
            try:
                while True:
                    ready, _, _ = select.select([self.request, channel], [], [], 30)
                    if self.request in ready:
                        data = self.request.recv(65536)
                        if not data: break
                        channel.sendall(data)
                    if channel in ready:
                        data = channel.recv(65536)
                        if not data: break
                        self.request.sendall(data)
            finally:
                channel.close()
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    with Server(("127.0.0.1", port), Forward) as server:
        print(f"SSH 隧道已就绪：http://127.0.0.1:{port}/ （Ctrl+C 关闭）", flush=True)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("bootstrap")
    execute = sub.add_parser("exec"); execute.add_argument("command")
    transfer = sub.add_parser("put"); transfer.add_argument("local"); transfer.add_argument("remote")
    forward = sub.add_parser("tunnel"); forward.add_argument("--port", type=int, default=18002)
    args = parser.parse_args()
    with connect() as client:
        if args.action == "bootstrap":
            raise SystemExit(run(client, "bash -se", (Path(__file__).parent / "bootstrap.sh").read_text()))
        if args.action == "exec":
            raise SystemExit(run(client, args.command))
        if args.action == "put":
            with client.open_sftp() as sftp:
                sftp.put(args.local, args.remote)
        if args.action == "tunnel":
            tunnel(client, args.port)


if __name__ == "__main__":
    main()
