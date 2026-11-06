"""交互配置服务器独立模型，Key 只走固定主机 SSH stdin，不进入命令参数。"""

import getpass
import json
import shlex
from urllib.parse import urlsplit
from remote import connect, run

name = input("模型名称：").strip()
base = input("OpenAI 兼容 Base URL（留空使用默认）：").strip()
key = getpass.getpass("本项目独立 API Key（隐藏输入）：").strip()
if not name or not key or any("\n" in x or "\r" in x for x in [name, base, key]):
    raise SystemExit("配置无效")
if base and (
    urlsplit(base).scheme != "https"
    or urlsplit(base).username
    or urlsplit(base).password
):
    raise SystemExit("远程模型接口必须使用 HTTPS，不能包含用户名密码")
values = {
    "MODEL_NAME": name,
    "MODEL_BASE_URL": base,
    "MODEL_API_KEY": key,
    "ALLOW_REAL_MODE": "1",
}
code = """import json,os,sys
from pathlib import Path
p=Path('/opt/personal-superagent/shared/runtime.env')
values=json.loads(sys.stdin.readline())
lines=[s for s in p.read_text().splitlines() if s.split('=',1)[0] not in values]
fd=os.open(str(p)+'.tmp',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f: f.write('\\n'.join(lines+[k+'='+v for k,v in values.items()])+'\\n')
os.chown(str(p)+'.tmp',p.stat().st_uid,p.stat().st_gid)
os.replace(str(p)+'.tmp',p)
"""
with connect() as client:
    result = run(client, "python3 -c " + shlex.quote(code), json.dumps(values) + "\n")
    if result:
        raise SystemExit(result)
    # 开启配置并不等于 ready，只有下一步显式验证通过才允许入队真实调用。
    raise SystemExit(
        run(
            client,
            "systemctl restart personal-superagent-web personal-superagent-worker",
        )
    )
