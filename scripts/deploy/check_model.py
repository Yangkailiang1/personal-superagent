"""用户显式执行才发出真实请求，不打印环境变量。"""

import shlex
from remote import connect, run

code = """import os,subprocess
from pathlib import Path
for line in Path('/opt/personal-superagent/shared/runtime.env').read_text().splitlines():
 if '=' in line:
  k,v=line.split('=',1);os.environ[k]=v
raise SystemExit(subprocess.call(['.venv/bin/python','manage.py','model_check']))
"""
with connect() as client:
    raise SystemExit(
        run(
            client,
            "cd /opt/personal-superagent/current && runuser -u superagent -- .venv/bin/python -c "
            + shlex.quote(code),
        )
    )
