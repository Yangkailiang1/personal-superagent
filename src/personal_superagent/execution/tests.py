"""接口用 Django 请求栈，领取/竞争用真实 PostgreSQL，执行用真实子进程。"""
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction, IntegrityError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from personal_superagent.tasks.models import Task
from .claims import claim_next, expire_leases, heartbeat
from .lifecycle import StateConflict, complete, enqueue, record_event, request_cancel
from .models import Attempt
from .processes import reconcile_interrupted
from .processes import confirm_dead
from .worker import Running, read_protocol, run_worker


class EndpointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner")
        self.other = get_user_model().objects.create_user("other")
        self.task = Task.objects.create(owner=self.user, title="test", description="统计文字")
        self.client.force_login(self.user)

    def enqueue(self):
        return enqueue(user=self.user, task_id=self.task.pk, request_key=uuid.uuid4(), mode="demo")

    def test_idempotent_start_and_conflicting_key(self):
        key = uuid.uuid4()
        first = enqueue(user=self.user, task_id=self.task.pk, request_key=key, mode="demo")
        second = enqueue(user=self.user, task_id=self.task.pk, request_key=key, mode="demo")
        self.assertEqual(first.pk, second.pk)
        with self.assertRaises(StateConflict):
            self.enqueue()
        with self.assertRaises(StateConflict):
            enqueue(user=self.user, task_id=self.task.pk, request_key=key, mode="real")

    def test_all_attempt_endpoints_check_owner(self):
        attempt = self.enqueue()
        self.client.force_login(self.other)
        urls = [
            ("post", reverse("attempt_start", args=[self.task.pk]), {"mode": "demo", "request_key": str(uuid.uuid4())}),
            ("post", reverse("attempt_cancel", args=[self.task.pk, attempt.pk]), {}),
            ("get", reverse("attempt_events", args=[self.task.pk, attempt.pk]), {}),
        ]
        for method, url, data in urls:
            self.assertEqual(getattr(self.client, method)(url, data).status_code, 404)

    def test_queued_cancel_and_retry_retains_history(self):
        attempt = self.enqueue()
        request_cancel(user=self.user, task_id=self.task.pk, attempt_id=attempt.pk)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "cancelled")
        second = enqueue(user=self.user, task_id=self.task.pk, request_key=uuid.uuid4(), mode="demo", retry=True)
        self.assertNotEqual(attempt.pk, second.pk)
        self.assertEqual(self.task.attempts.count(), 2)

    def test_event_cursor_and_csrf(self):
        attempt = self.enqueue()
        url = reverse("attempt_events", args=[self.task.pk, attempt.pk])
        data = self.client.get(url).json()
        self.assertEqual(data["cursor"], 1)
        self.assertEqual(self.client.get(url, {"after": 1}).json()["events"], [])
        self.assertEqual(self.client.get(url, {"after": -1}).status_code, 400)
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        self.assertEqual(browser.post(reverse("attempt_cancel", args=[self.task.pk, attempt.pk])).status_code, 403)

    def test_database_enforces_single_active_attempt(self):
        self.enqueue()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attempt.objects.create(task=self.task, request_key=uuid.uuid4(), mode="demo", input_snapshot={})

    def test_worker_refuses_sqlite(self):
        if connection.vendor == "sqlite":
            with self.assertRaises(CommandError):
                call_command("agent_worker", once=True)

    def test_pid_reuse_and_remote_host_are_not_confused(self):
        from types import SimpleNamespace
        import socket
        attempt = SimpleNamespace(hostname=socket.gethostname(), process_id=123, process_birth=100.0)
        with patch("personal_superagent.execution.processes.psutil.Process") as process:
            process.return_value.create_time.return_value = 200.0
            self.assertTrue(confirm_dead(attempt))
        attempt.hostname = "another-worker-host"
        self.assertFalse(confirm_dead(attempt))


@skipUnless(connection.vendor == "postgresql", "真实领取与子进程验收需要 PostgreSQL")
class PostgresExecutionTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("runner")

    def queued(self, mode="demo"):
        task = Task.objects.create(owner=self.user, title="整理任务", description="请统计这段文字。")
        return enqueue(user=self.user, task_id=task.pk, request_key=uuid.uuid4(), mode=mode)

    def command(self, *args, env=None):
        child_env = dict(os.environ, PGDATABASE=connection.settings_dict["NAME"])
        if env:
            child_env.update(env)
        return subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve().parents[3] / "manage.py"), "agent_worker", *args],
            env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )

    def wait_for(self, check, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(0.05)
        self.fail("等待执行状态超时")

    def test_atomic_claim_and_global_two_limit(self):
        for _ in range(3):
            self.queued()
        def claim(_):
            close_old_connections()
            try:
                item = claim_next(uuid.uuid4())
                return item.pk if item else None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=3) as pool:
            ids = [value for value in pool.map(claim, range(3)) if value]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(Attempt.objects.filter(state="queued").count(), 1)

    def test_concurrent_start_returns_same_attempt(self):
        task = Task.objects.create(owner=self.user, title="once", description="only once")
        key = uuid.uuid4()
        def start(_):
            close_old_connections()
            try:
                return enqueue(user=self.user, task_id=task.pk, request_key=key, mode="demo").pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(len(set(pool.map(start, range(2)))), 1)

    def test_expired_claim_cannot_submit_or_retry_until_reaped(self):
        queued = self.queued()
        attempt = claim_next(uuid.uuid4())
        Attempt.objects.filter(pk=attempt.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=30))
        self.assertFalse(heartbeat(attempt.pk, attempt.claim_token))
        expire_leases()
        self.assertFalse(record_event(attempt.pk, attempt.claim_token, "model", {}))
        with self.assertRaises(StateConflict):
            enqueue(user=self.user, task_id=queued.task_id, request_key=uuid.uuid4(), mode="demo", retry=True)
        self.assertFalse(complete(attempt.pk, attempt.claim_token, state="succeeded", result="late"))
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "interrupted")
        self.assertEqual(attempt.result, "")
        enqueue(user=self.user, task_id=queued.task_id, request_key=uuid.uuid4(), mode="demo", retry=True)

    def test_cancel_wins_against_late_success(self):
        self.queued()
        attempt = claim_next(uuid.uuid4())
        request_cancel(user=self.user, task_id=attempt.task_id, attempt_id=attempt.pk)
        complete(attempt.pk, attempt.claim_token, state="succeeded", result="late answer")
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "cancelled")
        self.assertEqual(attempt.result, "")

    def test_wrong_token_never_releases_claim(self):
        self.queued()
        attempt = claim_next(uuid.uuid4())
        self.assertFalse(complete(attempt.pk, uuid.uuid4(), state="succeeded", result="forged"))
        attempt.refresh_from_db()
        self.assertFalse(attempt.process_stopped)
        self.assertEqual(attempt.state, "running")

    def test_two_real_children_and_events(self):
        first, second = self.queued(), self.queued()
        worker = self.command("--once", "--concurrency", "2")
        try:
            _, error = worker.communicate(timeout=40)
            self.assertEqual(worker.returncode, 0, error.decode())
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
        first.refresh_from_db(); second.refresh_from_db()
        for attempt in [first, second]:
            self.assertEqual(attempt.state, "succeeded", attempt.error)
            self.assertIn("离线演示", attempt.result)
            self.assertTrue(attempt.process_stopped)
            self.assertIn("tool_end", list(attempt.events.values_list("kind", flat=True)))
            self.assertEqual(list(attempt.events.values_list("sequence", flat=True)), list(range(1, attempt.event_seq + 1)))
        self.assertLess(max(first.started_at, second.started_at), min(first.finished_at, second.finished_at))

    def test_real_mode_config_failure_is_not_demo(self):
        attempt = self.queued("real")
        worker = self.command("--once", env={"MODEL_API_KEY": "", "MODEL_NAME": ""})
        _, error = worker.communicate(timeout=40)
        self.assertEqual(worker.returncode, 0, error.decode())
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "failed")
        self.assertEqual(attempt.result, "")
        self.assertIn("ValueError", attempt.error)

    def sleeping_spawn(self, attempt):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        item = Running(attempt, process)
        threading.Thread(target=read_protocol, args=[item], daemon=True).start()
        return item

    def test_timeout_terminates_actual_process(self):
        attempt = self.queued()
        with patch("personal_superagent.execution.worker.spawn", side_effect=self.sleeping_spawn):
            run_worker(concurrency=1, timeout=1, once=True)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "failed")
        self.assertIn("超时", attempt.error)
        self.assertTrue(attempt.process_stopped)

    def test_running_cancellation_terminates_actual_process(self):
        attempt = self.queued()
        def cancel_later():
            close_old_connections()
            try:
                for _ in range(200):
                    if Attempt.objects.get(pk=attempt.pk).state == "running":
                        request_cancel(user=self.user, task_id=attempt.task_id, attempt_id=attempt.pk)
                        return
                    time.sleep(.02)
            finally:
                close_old_connections()
        thread = threading.Thread(target=cancel_later)
        thread.start()
        try:
            with patch("personal_superagent.execution.worker.spawn", side_effect=self.sleeping_spawn):
                run_worker(concurrency=1, timeout=10, once=True)
        finally:
            thread.join(timeout=5)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "cancelled")
        self.assertTrue(attempt.process_stopped)

    def test_worker_kill_then_restart_quarantines_and_reaps(self):
        attempt = self.queued()
        worker = self.command("--once")
        try:
            self.wait_for(lambda: Attempt.objects.filter(pk=attempt.pk, process_id__isnull=False).exists())
            worker.kill()
            worker.communicate(timeout=5)
            Attempt.objects.filter(pk=attempt.pk).update(heartbeat_at=timezone.now() - timedelta(seconds=30))
            # 真正启动第二个 Worker，执行启动核验；旧任务不会被再次领取。
            restarted = self.command("--once")
            _, error = restarted.communicate(timeout=15)
            self.assertEqual(restarted.returncode, 0, error.decode())
            self.wait_for(lambda: self.reaped(attempt.pk))
        finally:
            if worker.poll() is None:
                worker.kill(); worker.communicate()
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "interrupted")
        self.assertTrue(attempt.process_stopped)
        retry = enqueue(user=self.user, task_id=attempt.task_id, request_key=uuid.uuid4(), mode="demo", retry=True)
        self.assertNotEqual(retry.pk, attempt.pk)

    def reaped(self, attempt_id):
        reconcile_interrupted()
        return Attempt.objects.get(pk=attempt_id).process_stopped
