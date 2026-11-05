import os
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse

from personal_superagent.tasks.models import Task
from personal_superagent.workflow.checkpoints import checkpoint_dir
from .approvals import decide, resume
from .claims import claim_next
from .lifecycle import StateConflict, enqueue, request_cancel
from .models import Attempt


@skipUnless(connection.vendor == "postgresql", "需要真实 PostgreSQL 与子进程")
class WorkflowTests(TransactionTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"AGENT_RUNTIME_DIR": self.directory.name})
        self.env.start()
        self.user = get_user_model().objects.create_user("v03-owner")
        self.other = get_user_model().objects.create_user("v03-other")
        self.client.force_login(self.user)

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def queued(self):
        task = Task.objects.create(owner=self.user, title="读书计划", description="每周两小时，整理一个计划")
        return enqueue(user=self.user, task_id=task.pk, request_key=uuid.uuid4(), mode="demo")

    def worker(self):
        env = dict(os.environ, PGDATABASE=connection.settings_dict["NAME"])
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[3] / "manage.py"), "agent_worker", "--once"], env=env, capture_output=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def decision(self, attempt, decision="approve", request_key=None, version=None):
        approval = attempt.approvals.get()
        return decide(user=self.user, task_id=attempt.task_id, attempt_id=attempt.pk, approval_id=approval.pk,
                      expected_version=version or approval.version, request_key=request_key or uuid.uuid4(), decision=decision)

    def test_approval_releases_capacity_and_resume_does_not_repeat_agents(self):
        attempt = self.queued()
        self.worker(); attempt.refresh_from_db()
        self.assertEqual(attempt.state, "waiting_approval", attempt.error)
        self.assertTrue(attempt.process_stopped)
        self.assertEqual(attempt.artifacts.count(), 0)
        self.assertEqual(attempt.subtasks.filter(state="completed").count(), 2)
        self.assertTrue(all(item.namespace for item in attempt.subtasks.all()))
        self.assertEqual(claim_next(uuid.uuid4()), None)
        second = self.queued()
        claimed = claim_next(uuid.uuid4())
        self.assertEqual(claimed.pk, second.pk)  # 人工等待未占执行额度
        # 测试占用无需启动模型；先回收这份声明。
        from .lifecycle import complete
        complete(claimed.pk, claimed.claim_token, state="interrupted", error="fixture")
        key = uuid.uuid4()
        self.decision(attempt, request_key=key)
        self.decision(attempt, request_key=key, version=1)  # 相同请求幂等
        self.worker(); attempt.refresh_from_db()
        self.assertEqual(attempt.state, "succeeded", attempt.error)
        self.assertEqual(attempt.artifacts.count(), 1)
        self.assertEqual(attempt.events.filter(kind="subagent_start").count(), 2)
        item = attempt.artifacts.get()
        download = self.client.get(reverse("artifact", args=[attempt.task_id, attempt.pk, item.pk]), {"download": 1})
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"# ", b"".join(download.streaming_content))
        self.assertContains(self.client.get(reverse("task_detail", args=[attempt.task_id])), "最终回答")

    def test_reject_does_not_publish_document(self):
        attempt = self.queued(); self.worker()
        self.decision(attempt, "reject"); self.worker(); attempt.refresh_from_db()
        self.assertEqual(attempt.state, "succeeded", attempt.error)
        self.assertEqual(attempt.artifacts.count(), 0)
        self.assertIn("拒绝", attempt.result)

    def test_cancel_waiting_closes_approval_and_prevents_decision(self):
        attempt = self.queued(); self.worker()
        request_cancel(user=self.user, task_id=attempt.task_id, attempt_id=attempt.pk)
        with self.assertRaises(StateConflict):
            self.decision(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "cancelled")
        self.assertEqual(attempt.approvals.get().decision, "cancelled")
        self.assertEqual(attempt.artifacts.count(), 0)

    def test_approval_version_conflict_and_cross_user_access(self):
        attempt = self.queued(); self.worker()
        with self.assertRaises(StateConflict):
            self.decision(attempt, version=99)
        self.client.force_login(self.other)
        approval = attempt.approvals.get()
        self.assertEqual(self.client.post(reverse("approval_decide", args=[attempt.task_id, attempt.pk, approval.pk]), {"version": 1, "request_key": str(uuid.uuid4()), "decision": "approve"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("attempt_resume", args=[attempt.task_id, attempt.pk])).status_code, 404)
        self.client.force_login(self.user)
        self.decision(attempt); self.worker()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("artifact", args=[attempt.task_id, attempt.pk, attempt.artifacts.get().pk])).status_code, 404)

    def test_lost_business_projection_recovered_from_checkpoint(self):
        attempt = self.queued(); self.worker()
        # 模拟 checkpoint 已提交，但 Worker 在业务投影落库前丢失。
        attempt.approvals.all().delete(); attempt.subtasks.all().delete()
        Attempt.objects.filter(pk=attempt.pk).update(state="interrupted", process_stopped=True)
        Task.objects.filter(pk=attempt.task_id).update(status="interrupted")
        resume(user=self.user, task_id=attempt.task_id, attempt_id=attempt.pk)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "waiting_approval")
        self.assertEqual(attempt.approvals.count(), 1)
        self.assertEqual(attempt.subtasks.count(), 2)
        self.decision(attempt); self.worker()
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "succeeded", attempt.error)

    def test_corrupt_checkpoint_resume_rejected(self):
        attempt = self.queued(); self.worker()
        (checkpoint_dir(attempt.pk) / "checkpoint.sqlite3").write_bytes(b"corrupt")
        Attempt.objects.filter(pk=attempt.pk).update(state="interrupted", process_stopped=True)
        Task.objects.filter(pk=attempt.task_id).update(status="interrupted")
        with self.assertRaises(StateConflict):
            resume(user=self.user, task_id=attempt.task_id, attempt_id=attempt.pk)

    def test_old_attempt_has_no_resume(self):
        attempt = self.queued()
        Attempt.objects.filter(pk=attempt.pk).update(state="interrupted", process_stopped=True, workflow_version="", hostname=socket.gethostname())
        Task.objects.filter(pk=attempt.task_id).update(status="interrupted")
        with self.assertRaises(StateConflict):
            resume(user=self.user, task_id=attempt.task_id, attempt_id=attempt.pk)
