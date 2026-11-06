"""两份独立本机运行目录与真实 HTTP/子进程；不冒称不同物理机器。"""

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from django.test import LiveServerTestCase
from django.contrib.auth import get_user_model
from personal_superagent.devices.auth import pair, new_pairing
from personal_superagent.client.config import save
from personal_superagent.client.worker_agent import profiles
from personal_superagent.execution.claims import claim_next
from personal_superagent.execution.models import Attempt
from personal_superagent.execution.approvals import decide
from personal_superagent.intake.models import Conversation
from .models import AgentProfile
from .routing import dispatch_pending
from .device_jobs import hello
from .plans import publish
from .tests import PLAN, POLICY


class IndependentDevicesTests(LiveServerTestCase):
    def test_two_real_clients_complete_independent_graphs_and_approvals(self):
        user = get_user_model().objects.create_user("two-device-owner")
        configs = []
        with tempfile.TemporaryDirectory() as directory:
            for index in range(2):
                root = Path(directory) / str(index)
                root.mkdir(mode=0o700)
                device, token = pair(new_pairing(user), "测试设备" + str(index))
                config = {
                    "url": self.live_server_url,
                    "device_id": str(device.pk),
                    "token": token,
                    "roots": [],
                }
                save(root, config)
                hello(device, {"grants": [], "profiles": profiles(root, config)})
                agent = AgentProfile.objects.get(
                    device=device, role="writer", grant=None
                )
                configs.append((root, agent))
            plan = {
                **PLAN,
                "steps": [
                    {**PLAN["steps"][0], "key": "work" + str(i), "agent_id": str(a.pk)}
                    for i, (_, a) in enumerate(configs)
                ],
            }
            c = Conversation.objects.create(owner=user, plan_mode=True, draft=plan)
            release = publish(
                user,
                c.pk,
                {"version": 1, "request_key": str(uuid.uuid4()), "policy": POLICY},
            )
            dispatch_pending()
            # 路由建议也通过真实 Worker 子进程；之后 dispatch 将任务交给指定设备。
            env = {
                **os.environ,
                "PGDATABASE": __import__(
                    "django.conf", fromlist=["settings"]
                ).settings.DATABASES["default"]["NAME"],
            }
            worker = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "agent_worker",
                    "--once",
                    "--concurrency",
                    "2",
                ],
                capture_output=True,
                env=env,
                timeout=60,
            )
            self.assertEqual(worker.returncode, 0, worker.stderr.decode())
            dispatch_pending()
            self.assertTrue(all(t.execution_agent_id for t in release.tasks.all()))
            self.assertIsNone(claim_next(uuid.uuid4()))  # 云端不可领取本机任务

            def run(item):
                process = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import sys;from pathlib import Path;from personal_superagent.client.worker_agent import run;run(Path(sys.argv[1]),once=True)",
                        str(item[0]),
                    ],
                    capture_output=True,
                    timeout=60,
                )
                self.assertEqual(
                    process.returncode,
                    0,
                    process.stderr.decode() + process.stdout.decode(),
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(run, configs))
            attempts = list(Attempt.objects.filter(task__release=release))
            self.assertEqual(len(attempts), 2)
            for a in attempts:
                self.assertEqual(a.state, "waiting_approval", a.error)
                self.assertTrue(a.process_stopped)
                approval = a.approvals.get(decision="pending")
                decide(
                    user=user,
                    task_id=a.task_id,
                    attempt_id=a.pk,
                    approval_id=approval.pk,
                    expected_version=approval.version,
                    request_key=uuid.uuid4(),
                    decision="approve",
                )
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(run, configs))
            for a in attempts:
                a.refresh_from_db()
                self.assertEqual(a.state, "succeeded", a.error)
                self.assertEqual(a.artifacts.count(), 1)
                self.assertTrue(a.events.filter(kind="device_cursor").exists())
