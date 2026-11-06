"""独立工具凭证经固定 SSH stdin 配置，不复用旧项目密钥。"""

import getpass
import json
import shlex
from pathlib import Path
from remote import connect, run

values = {}
for name, label in [
    ("TAVILY_API_KEY", "Tavily Key"),
    ("IMAGE_API_KEY", "生图 Key"),
    ("IMAGE_MODEL_NAME", "生图模型"),
    ("IMAGE_BASE_URL", "生图 Base URL"),
]:
    value = getpass.getpass(label + "（隐藏输入，留空保留）：").strip()
    if "\n" in value or "\r" in value:
        raise SystemExit("配置不得换行")
    if value:
        values[name] = value
file = input("云端 MCP JSON 配置文件路径（留空不变）：").strip()
if file:
    from personal_superagent.collaboration.toolkit import validate_mcp

    data = json.loads(Path(file).expanduser().read_text())
    validate_mcp(data)
    values["MCP_CONFIG"] = json.dumps(data)
if not values:
    raise SystemExit("未修改配置")
code = """import json,os,sys
from pathlib import Path
p=Path('/opt/personal-superagent/shared/runtime.env');values=json.loads(sys.stdin.readline())
lines=[line for line in p.read_text().splitlines() if line.split('=',1)[0] not in values]
fd=os.open(str(p)+'.tmp',os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
with os.fdopen(fd,'w') as f:f.write('\\n'.join(lines+[k+'='+v for k,v in values.items()])+'\\n')
os.chown(str(p)+'.tmp',p.stat().st_uid,p.stat().st_gid);os.replace(str(p)+'.tmp',p)
"""
with connect() as client:
    result = run(client, "python3 -c " + shlex.quote(code), json.dumps(values) + "\n")
    if result:
        raise SystemExit(result)
    raise SystemExit(
        run(
            client,
            "systemctl restart personal-superagent-web personal-superagent-worker",
        )
    )
