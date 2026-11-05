"""在安全终端输入密码，经 SSH stdin 创建本人账号；不提供默认密码。"""
from getpass import getpass
import json
from remote import connect, run

username = input("新账号用户名：").strip()
password = getpass("新账号密码（不会显示）：")
if password != getpass("再次输入密码："):
    raise SystemExit("两次密码不同，未创建账号")
code = '''import json, sys, os
from pathlib import Path
for line in Path('/opt/personal-superagent/shared/runtime.env').read_text().splitlines():
    if '=' in line:
        k,v=line.split('=',1); os.environ[k]=v
import django
django.setup()
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
data=json.loads(sys.stdin.readline())
User=get_user_model()
if not data['username'] or User.objects.filter(username=data['username']).exists():
    raise SystemExit('用户名为空或已存在，未修改任何账号')
user=User(username=data['username'])
validate_password(data['password'], user=user)
user.set_password(data['password']); user.save()
print('本人账号已创建；未设置任何默认密码。')
'''
import shlex
command = "cd /opt/personal-superagent/current && runuser -u superagent -- .venv/bin/python -c " + shlex.quote(code)
with connect() as client:
    raise SystemExit(run(client, command, json.dumps({"username": username, "password": password}) + "\n"))
