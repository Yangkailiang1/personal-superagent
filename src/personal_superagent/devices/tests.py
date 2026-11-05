import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, LiveServerTestCase
from django.utils import timezone

from personal_superagent.execution.approvals import decide
from personal_superagent.execution.lifecycle import enqueue, request_cancel
from personal_superagent.execution.models import Attempt
from personal_superagent.tasks.models import Task
from .auth import digest, new_pairing, pair
from .models import Device, Grant, LocalOperation, Pairing
from .protocol import poll, report, sweep, validate_lease


class DeviceSecurityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("device-owner")
        self.other = get_user_model().objects.create_user("other-owner")
        self.device, self.token = pair(new_pairing(self.user), "测试电脑")
        self.session = uuid.uuid4()
        self.grant_id = uuid.uuid4()
        self.manifest = [
            {
                "id": str(self.grant_id),
                "label": "notes",
                "tools": ["read_text", "write_text"],
            }
        ]
        poll(self.device.pk, self.session, self.manifest, connect=True)

    def operation(self, tool="read_text"):
        grant = Grant.objects.get(pk=self.grant_id)
        task = Task.objects.create(
            owner=self.user, title="test", description="device", status="waiting_device"
        )
        attempt = Attempt.objects.create(
            task=task,
            request_key=uuid.uuid4(),
            mode="demo",
            input_snapshot={},
            state="waiting_device",
            checkpoint_id="cp",
        )
        return LocalOperation.objects.create(
            attempt=attempt,
            grant=grant,
            grant_revision=grant.revision,
            source_id=str(uuid.uuid4()),
            interrupt_id=str(uuid.uuid4()),
            checkpoint_id="cp",
            tool=tool,
            arguments={"path": "file"},
        )

    def test_pairing_single_use_expiry_and_hash_only(self):
        code = new_pairing(self.user)
        self.assertNotEqual(Pairing.objects.get(code_hash=digest(code)).code_hash, code)
        pair(code, "once")
        with self.assertRaises(ValueError):
            pair(code, "again")
        expired = new_pairing(self.user)
        Pairing.objects.filter(code_hash=digest(expired)).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(ValueError):
            pair(expired, "expired")
        self.assertNotEqual(
            Device.objects.get(pk=self.device.pk).token_hash, self.token
        )

    def test_api_bearer_not_session_and_csrf_required_for_browser(self):
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.post(
                "/api/device/poll/",
                data=json.dumps({}),
                content_type="application/json",
            ).status_code,
            401,
        )
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        self.assertEqual(
            browser.post(
                "/api/pairing/", {}, content_type="application/json"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/device/pair/", data="[]", content_type="application/json"
            ).status_code,
            400,
        )

    def test_revoke_does_not_get_undone_by_client_sync(self):
        grant = Grant.objects.get(pk=self.grant_id)
        grant.revoked_at = timezone.now()
        grant.save()
        poll(self.device.pk, self.session, self.manifest)
        grant.refresh_from_db()
        self.assertIsNotNone(grant.revoked_at)
        operation = self.operation()
        sweep()
        operation.refresh_from_db()
        self.assertEqual(operation.state, "failed")

    def test_session_replacement_and_no_automatic_reclaim(self):
        operation = self.operation()
        leased = poll(self.device.pk, self.session, self.manifest)["operation"]
        self.assertIsNotNone(leased)
        self.assertIsNone(
            poll(self.device.pk, self.session, self.manifest)["operation"]
        )
        LocalOperation.objects.filter(pk=operation.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        sweep()
        operation.refresh_from_db()
        self.assertEqual(operation.state, "uncertain")
        self.assertIsNone(
            poll(self.device.pk, self.session, self.manifest)["operation"]
        )
        new_session = uuid.uuid4()
        poll(self.device.pk, new_session, self.manifest, connect=True)
        with self.assertRaises(ValueError):
            poll(self.device.pk, self.session, self.manifest)

    def test_receipt_idempotency_and_cancellation_fence(self):
        operation = self.operation()
        leased = poll(self.device.pk, self.session, self.manifest)["operation"]
        validate_lease(self.device, operation.pk, leased["lease"])
        report(
            self.device, operation.pk, leased["lease"], "succeeded", {"text": "actual"}
        )
        report(
            self.device, operation.pk, leased["lease"], "succeeded", {"text": "actual"}
        )
        with self.assertRaises(ValueError):
            report(
                self.device,
                operation.pk,
                leased["lease"],
                "succeeded",
                {"text": "changed"},
            )
        second = self.operation("write_text")
        leased = poll(self.device.pk, self.session, self.manifest)["operation"]
        request_cancel(
            user=self.user, task_id=second.attempt.task_id, attempt_id=second.attempt_id
        )
        report(self.device, second.pk, leased["lease"], "succeeded", {"created": True})
        second.refresh_from_db()
        second.attempt.refresh_from_db()
        self.assertEqual(second.state, "uncertain")
        self.assertEqual(second.attempt.state, "cancelled")

    def test_cross_user_device_and_task_scope_denied(self):
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.post(
                "/api/revoke/",
                data=json.dumps({"device_id": str(self.device.pk)}),
                content_type="application/json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/api/create/",
                data=json.dumps({"text": "bad", "grant_id": str(self.grant_id)}),
                content_type="application/json",
            ).status_code,
            404,
        )


@skipUnless(connection.vendor == "postgresql", "需要真实 PostgreSQL、HTTP 和子进程")
class DeviceFlowTests(LiveServerTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.environment = patch.dict(
            os.environ, {"AGENT_RUNTIME_DIR": str(self.base / "runtime")}
        )
        self.environment.start()
        self.user = get_user_model().objects.create_user("local-e2e")
        self.materials = self.base / "materials"
        self.materials.mkdir()
        (self.materials / "input.md").write_text(
            "# 本机材料\nDEVICE_SENTINEL_91：每周学习 Python 两小时。"
        )
        self.config = self.base / "client"
        self.cli(
            "pair",
            "--url",
            self.live_server_url,
            "--code",
            new_pairing(self.user),
            "--name",
            "真实客户端",
        )
        self.cli(
            "grant",
            "--name",
            "notes",
            "--path",
            str(self.materials),
            "--tools",
            "list_files,read_text,write_text",
            "--ack-cloud-transfer",
        )
        self.cli("run", "--once")

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def cli(self, *args):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "personal_superagent.client.cli",
                "--config-dir",
                str(self.config),
                *args,
            ],
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode, 0, result.stdout.decode() + result.stderr.decode()
        )

    def worker(self):
        env = dict(os.environ, PGDATABASE=connection.settings_dict["NAME"])
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[3] / "manage.py"),
                "agent_worker",
                "--once",
            ],
            env=env,
            capture_output=True,
            timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_real_cloud_local_read_approve_write_and_artifact(self):
        grant = Grant.objects.get(device__owner=self.user)
        task = Task.objects.create(
            owner=self.user,
            title="整理本机材料",
            description="读取并整理授权材料",
            local_grant=grant,
        )
        attempt = enqueue(
            user=self.user, task_id=task.pk, request_key=uuid.uuid4(), mode="demo"
        )
        for _ in range(12):
            attempt.refresh_from_db()
            if attempt.state == "queued":
                self.worker()
            elif attempt.state == "waiting_device":
                self.cli("run", "--once")
            elif attempt.state == "waiting_approval":
                approval = attempt.approvals.filter(decision="pending").first()
                if approval.action["name"] == "local_write_text":
                    self.assertFalse((self.materials / "superagent-result.md").exists())
                decide(
                    user=self.user,
                    task_id=task.pk,
                    attempt_id=attempt.pk,
                    approval_id=approval.pk,
                    expected_version=approval.version,
                    request_key=uuid.uuid4(),
                    decision="approve",
                )
            elif attempt.state == "succeeded":
                break
            else:
                self.fail(attempt.state + ": " + attempt.error)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "succeeded", attempt.error)
        self.assertIn(
            "DEVICE_SENTINEL_91", (self.materials / "superagent-result.md").read_text()
        )
        self.assertIn("DEVICE_SENTINEL_91", attempt.artifacts.get().content)
        self.assertEqual(attempt.local_operations.filter(state="succeeded").count(), 3)
        # 凭证和本地绝对路径没有进入业务输入快照。
        self.assertNotIn(str(self.materials), json.dumps(attempt.input_snapshot))
