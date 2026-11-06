"""PostgreSQL 控制面验收；固定回执不冒充真实 Claude 模型执行。"""

import uuid
from datetime import timedelta
from django.test import TransactionTestCase, Client
from django.http import Http404
from django.utils import timezone
from django.contrib.auth import get_user_model
from personal_superagent.devices.auth import pair, new_pairing
from personal_superagent.collaboration.models import AgentProfile
from personal_superagent.collaboration.plans import publish
from personal_superagent.collaboration.tests import PLAN, POLICY
from personal_superagent.collaboration.routing import dispatch_pending
from personal_superagent.intake.models import Conversation
from personal_superagent.execution.lifecycle import (
    enqueue,
    request_cancel,
    StateConflict,
)
from personal_superagent.execution.claims import claim_next, expire_leases
from personal_superagent.execution.models import Attempt
from .models import Repository, ExternalRun, Permission
from .services import hello, claim, control, decide, snapshot


class HappierTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "happier-owner", password="test-pass"
        )
        self.other = get_user_model().objects.create_user("other-owner")
        self.device, self.token = pair(new_pairing(self.user), "本机")
        self.repo_id = str(uuid.uuid4())
        self.manifest = {
            "id": self.repo_id,
            "label": "测试仓库",
            "baseline": "a" * 40,
            "policy": {
                "write_paths": ["src"],
                "checks": [],
                "max_turns": 4,
                "timeout": 60,
            },
        }
        hello(self.device, {"ready": True, "repositories": [self.manifest]})
        self.repo = Repository.objects.get(pk=self.repo_id)
        step = {
            **PLAN["steps"][0],
            "role": "coder",
            "agent_id": str(self.repo.agent_id),
            "tools": ["repository_read", "repository_write", "repository_command"],
            "repository_id": self.repo_id,
            "repository_version": 1,
            "base_commit": "a" * 40,
            "write_paths": ["src"],
            "checks": [],
        }
        self.c = Conversation.objects.create(
            owner=self.user, plan_mode=True, draft={**PLAN, "steps": [step]}
        )
        self.release = publish(
            self.user,
            self.c.pk,
            {
                "version": 1,
                "request_key": str(uuid.uuid4()),
                "policy": {**POLICY, "mode": "real"},
            },
        )
        dispatch_pending()
        self.task = self.release.tasks.get()
        self.task.refresh_from_db()
        self.assertIsNone(claim_next(uuid.uuid4()))
        self.job = claim(self.device)["job"]
        self.assertIsNotNone(self.job)
        self.a = Attempt.objects.get(pk=self.job["id"])
        self.seq = 0

    def send(self, action, **kwargs):
        return control(self.device, {**self.job, "action": action, **kwargs})

    def event(self, kind, **kwargs):
        self.seq += 1
        return self.send("event", sequence=self.seq, event={"kind": kind, **kwargs})

    def test_dispatch_approval_collection_and_idempotency(self):
        self.assertEqual(self.a.executor_kind, "happier")
        self.assertIsNone(claim(self.device)["job"])
        self.event("session", session_id="claude-session")
        self.event(
            "permission",
            request_id="tool1",
            tool="Bash",
            args={"command": "unrecognized"},
        )
        self.a.refresh_from_db()
        self.assertEqual(self.a.state, "waiting_approval")
        self.assertFalse(self.a.process_stopped)
        self.assertTrue(snapshot(self.a)["can_decide"])
        p = self.a.external_run.permissions.get()
        with self.assertRaises(Http404):
            decide(
                self.other,
                {
                    "id": p.pk,
                    "version": 1,
                    "request_key": str(uuid.uuid4()),
                    "decision": "approve",
                },
            )
        key = str(uuid.uuid4())
        data = {"id": p.pk, "version": 1, "request_key": key, "decision": "approve"}
        decide(self.user, data)
        decide(self.user, data)
        with self.assertRaises(StateConflict):
            decide(self.user, {**data, "request_key": str(uuid.uuid4())})
        self.assertEqual(self.send("heartbeat")["decisions"][0]["request_id"], "tool1")
        self.event("permission_applied", request_id="tool1", decision="approve")
        report = {
            "state": "succeeded",
            "text": "done",
            "files": [],
            "checks": [],
            "violations": [],
        }
        self.send("result", report=report)
        self.send("result", report=report)
        self.a.refresh_from_db()
        self.assertEqual(self.a.state, "succeeded")
        self.assertEqual(self.a.result, "done")
        self.assertTrue(self.a.process_stopped)
        with self.assertRaises(StateConflict):
            self.send("result", report={**report, "text": "replace"})

    def test_cancel_does_not_claim_process_stopped_or_accept_late_success(self):
        self.event(
            "permission", request_id="p", tool="Bash", args={"command": "rm -rf src"}
        )
        request_cancel(user=self.user, task_id=self.task.pk, attempt_id=self.a.pk)
        self.a.refresh_from_db()
        self.assertFalse(self.a.process_stopped)
        self.assertFalse(self.send("heartbeat")["continue"])
        self.assertFalse(snapshot(self.a)["can_decide"])
        self.send("result", report={"state": "succeeded", "text": "late"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.state, "cancelled")
        self.assertEqual(self.a.result, "")

    def test_expired_approval_lease_and_old_results(self):
        self.event(
            "permission", request_id="p", tool="Bash", args={"command": "custom"}
        )
        Attempt.objects.filter(pk=self.a.pk).update(
            heartbeat_at=timezone.now() - timedelta(seconds=30)
        )
        expire_leases()
        self.a.refresh_from_db()
        self.assertEqual(self.a.state, "interrupted")
        self.send("result", report={"state": "succeeded", "text": "stale"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.state, "interrupted")
        self.assertEqual(self.a.result, "")

    def test_revoke_and_permission_content_conflict(self):
        self.event(
            "permission", request_id="p", tool="Bash", args={"command": "custom"}
        )
        with self.assertRaises(StateConflict):
            self.event(
                "permission", request_id="p", tool="Bash", args={"command": "changed"}
            )
        hello(self.device, {"ready": True, "repositories": []})
        self.assertFalse(self.send("heartbeat")["continue"])

    def test_owner_endpoints_and_csrf(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.other)
        self.assertEqual(c.get("/api/happier/repositories/").json()["items"], [])
        self.assertEqual(
            c.post(
                "/api/happier/decide/", data="{}", content_type="application/json"
            ).status_code,
            403,
        )


from django.test import LiveServerTestCase
from unittest.mock import patch
import tempfile, time, json, subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from personal_superagent.client.config import save as save_client
from personal_superagent.client.happier.repositories import register, manifest
from personal_superagent.client.happier.worker import (
    execute,
    recover,
    control as client_control,
)
from personal_superagent.client.happier.ledger import Ledger


class HappierTransportTests(LiveServerTestCase):
    def test_real_http_node_worktree_approval_and_receipt(self):
        user = get_user_model().objects.create_user("http-owner")
        device, token = pair(new_pairing(user), "HTTP 客户端")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "client"
            root.mkdir()
            repo = Path(directory) / "repo"
            repo.mkdir()

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL
                )

            git("init")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (repo / "base.txt").write_text("base")
            git("add", ".")
            git("commit", "-m", "base")
            (repo / "base.txt").write_text("user dirty")
            registry = register(
                root, "HTTP repo", repo, ["src"], ["git status --short"], "HEAD"
            )
            hello(device, {"ready": True, "repositories": manifest(root)})
            binding = Repository.objects.get(pk=registry["id"])
            step = {
                **PLAN["steps"][0],
                "role": "coder",
                "agent_id": str(binding.agent_id),
                "tools": ["repository_write"],
                "repository_id": str(binding.pk),
                "repository_version": 1,
                "base_commit": binding.baseline,
                "write_paths": ["src"],
                "checks": ["git status --short"],
            }
            c = Conversation.objects.create(
                owner=user, plan_mode=True, draft={**PLAN, "steps": [step]}
            )
            release = publish(
                user,
                c.pk,
                {
                    "version": 1,
                    "request_key": str(uuid.uuid4()),
                    "policy": {**POLICY, "mode": "real"},
                },
            )
            dispatch_pending()
            job = claim(device)["job"]
            config = {
                "url": self.live_server_url,
                "device_id": str(device.pk),
                "token": token,
                "roots": [],
            }
            save_client(root, config)
            fixture = (
                Path(__file__).resolve().parents[3]
                / "tests/fixtures/claude-recorded-executor.mjs"
            )

            def client():
                db = Ledger(root)
                try:
                    execute(root, config, db, job)
                finally:
                    db.db.close()

            def lost_receipt(config, job, action, **data):
                response = client_control(config, job, action, **data)
                if action == "result":
                    raise OSError("固定故障：服务器已接收结果，但回执丢失")
                return response

            with (
                patch(
                    "personal_superagent.client.happier.worker.control",
                    side_effect=lost_receipt,
                ),
                patch("personal_superagent.client.happier.worker.EXECUTOR", fixture),
                ThreadPoolExecutor() as pool,
            ):
                running = pool.submit(client)
                deadline = time.monotonic() + 20
                while (
                    not Permission.objects.filter(run__attempt_id=job["id"]).exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.1)
                permission = Permission.objects.get(run__attempt_id=job["id"])
                decide(
                    user,
                    {
                        "id": permission.pk,
                        "version": 1,
                        "request_key": str(uuid.uuid4()),
                        "decision": "reject",
                    },
                )
                with self.assertRaises(OSError):
                    running.result(timeout=25)
            # 模拟客户端重启：只补传账本回执，不再启动 Node 或创建 worktree。
            db = Ledger(root)
            recover(config, db)
            self.assertFalse(db.unfinished())
            db.db.close()
            self.assertEqual(len(list((root / "worktrees").iterdir())), 1)
            attempt = Attempt.objects.get(pk=job["id"])
            self.assertEqual(attempt.state, "succeeded", attempt.error)
            self.assertEqual(
                attempt.external_run.report["files"][0]["content"], "recorded output"
            )
            self.assertEqual(attempt.external_run.report["checks"][0]["exit_code"], 0)
            self.assertEqual((repo / "base.txt").read_text(), "user dirty")
            self.assertFalse((repo / "src").exists())
            self.assertTrue(Permission.objects.get(pk=permission.pk).applied)
