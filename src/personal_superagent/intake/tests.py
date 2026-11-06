import json
import os
import subprocess
import sys
import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, Client
from django.http import Http404
from personal_superagent.execution.lifecycle import StateConflict, enqueue
from personal_superagent.execution.models import Attempt
from personal_superagent.tasks.models import Task
from .models import Conversation, Confirmation
from .services import send, edit, confirm
from .agent import run_intake

DRAFT = {
    "title": "学习计划",
    "goal": "整理材料",
    "materials": "用户提供",
    "deliverables": ["文档"],
    "acceptance": ["覆盖目标"],
    "questions": [],
    "assumptions": [],
    "device_needs": "无需本地工具",
}


class IntakeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("intake-owner")
        self.other = get_user_model().objects.create_user("intake-other")
        self.c = Conversation.objects.create(owner=self.user, draft=DRAFT)
        self.client.force_login(self.user)

    def test_confirmation_atomic_idempotent_and_versioned(self):
        data = {"version": 1, "request_key": str(uuid.uuid4())}
        first = confirm(self.user, self.c.pk, data)
        self.assertEqual(confirm(self.user, self.c.pk, data), first)
        self.assertEqual(
            confirm(self.user, self.c.pk, {**data, "request_key": str(uuid.uuid4())}),
            first,
        )
        self.assertEqual(Confirmation.objects.count(), 1)
        edit(self.user, self.c.pk, {"version": 1, "draft": {**DRAFT, "goal": "新目标"}})
        with self.assertRaises(StateConflict):
            confirm(
                self.user, self.c.pk, {"version": 1, "request_key": str(uuid.uuid4())}
            )
        newer = confirm(
            self.user, self.c.pk, {"version": 2, "request_key": str(uuid.uuid4())}
        )
        self.assertNotEqual(newer, first)
        first.refresh_from_db()
        self.assertIn("整理材料", first.description)

    def test_questions_and_assumptions_block_publish(self):
        self.c.draft = {**DRAFT, "questions": ["输出格式？"]}
        self.c.save()
        with self.assertRaises(StateConflict):
            confirm(
                self.user, self.c.pk, {"version": 1, "request_key": str(uuid.uuid4())}
            )
        self.c.draft = {**DRAFT, "assumptions": ["只用用户材料"]}
        self.c.save()
        with self.assertRaises(StateConflict):
            confirm(
                self.user, self.c.pk, {"version": 1, "request_key": str(uuid.uuid4())}
            )
        self.assertEqual(Task.objects.count(), 0)

    def test_turn_idempotent_busy_edit_and_internal_start_denied(self):
        data = {
            "text": "整理材料",
            "mode": "demo",
            "version": 1,
            "request_key": str(uuid.uuid4()),
        }
        turn = send(self.user, self.c.pk, data)
        self.assertEqual(send(self.user, self.c.pk, data), turn)
        with self.assertRaises(StateConflict):
            send(self.user, self.c.pk, {**data, "request_key": str(uuid.uuid4())})
        with self.assertRaises(StateConflict):
            edit(self.user, self.c.pk, {"version": 1, "draft": DRAFT})
        with self.assertRaises(StateConflict):
            enqueue(
                user=self.user,
                task_id=turn.attempt.task_id,
                request_key=uuid.uuid4(),
                mode="demo",
            )

    def test_cross_owner_csrf_and_model_status(self):
        with self.assertRaises(Http404):
            confirm(self.other, self.c.pk, {})
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(
                "/api/intake/conversation/", {"id": str(self.c.pk)}
            ).status_code,
            404,
        )
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(
            csrf.post(
                "/api/intake/conversations/", {}, content_type="application/json"
            ).status_code,
            403,
        )
        with patch.dict(os.environ, {"MODEL_API_KEY": "", "MODEL_NAME": ""}):
            self.assertEqual(
                self.client.get("/api/dashboard/").json()["model"]["state"],
                "unconfigured",
            )

    def test_real_intake_requires_validated_configuration(self):
        with patch(
            "personal_superagent.model_status.status",
            return_value={"state": "unverified"},
        ):
            with self.assertRaises(StateConflict):
                send(
                    self.user,
                    self.c.pk,
                    {
                        "text": "整理",
                        "mode": "real",
                        "version": 1,
                        "request_key": str(uuid.uuid4()),
                    },
                )

    def test_board_mapping_pagination_and_internal_jobs_hidden(self):
        for state in [
            "pending",
            "queued",
            "running",
            "waiting_device",
            "waiting_approval",
            "failed",
            "interrupted",
            "succeeded",
            "cancelled",
        ]:
            Task.objects.create(
                owner=self.user, title=state, description="x", status=state
            )
        Task.objects.create(owner=self.other, title="private", description="secret")
        send(
            self.user,
            self.c.pk,
            {
                "text": "内部",
                "mode": "demo",
                "version": 1,
                "request_key": str(uuid.uuid4()),
            },
        )
        board = self.client.get("/api/dashboard/").json()
        self.assertEqual(board["total"], 9)  # 八个非取消任务 + 一个草稿
        self.assertNotIn("private", str(board))
        self.assertNotIn("需求接待", str(board))
        for _ in range(35):
            Task.objects.create(owner=self.user, title="分页", description="x")
        page = self.client.get("/api/dashboard/", {"page": 2}).json()
        self.assertEqual(page["page"], 2)
        self.assertEqual(len(self.client.get("/api/dashboard/").json()["items"]), 30)
        self.assertEqual(
            self.client.get("/api/dashboard/", {"history": "1"}).json()["total"], 1
        )

    def test_demo_uses_native_graph_and_only_draft_tool(self):
        result = json.loads(
            run_intake(
                {"messages": [], "text": "需求哨兵", "draft": {}},
                "demo",
                lambda *a: None,
            )
        )
        self.assertIn("需求哨兵", result["draft"]["goal"])
        self.assertIn("离线演示", result["reply"])


class SharedQuotaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("shared-quota")
        self.c = Conversation.objects.create(owner=self.user)

    def test_intake_and_background_share_global_slots(self):
        from personal_superagent.execution.claims import claim_next

        send(
            self.user,
            self.c.pk,
            {
                "text": "整理",
                "mode": "demo",
                "version": 1,
                "request_key": str(uuid.uuid4()),
            },
        )
        for _ in range(2):
            task = Task.objects.create(owner=self.user, title="后台", description="x")
            enqueue(
                user=self.user, task_id=task.pk, request_key=uuid.uuid4(), mode="demo"
            )
        self.assertIsNotNone(claim_next(uuid.uuid4()))
        self.assertIsNotNone(claim_next(uuid.uuid4()))
        self.assertIsNone(claim_next(uuid.uuid4()))


class IntakeWorkerTests(TransactionTestCase):
    def test_worker_projects_then_user_confirms_and_starts(self):
        user = get_user_model().objects.create_user("intake-worker")
        c = Conversation.objects.create(owner=user)
        turn = send(
            user,
            c.pk,
            {
                "text": "整理每周学习计划",
                "mode": "demo",
                "version": 1,
                "request_key": str(uuid.uuid4()),
            },
        )
        result = subprocess.run(
            [sys.executable, "manage.py", "agent_worker", "--once"],
            capture_output=True,
            timeout=60,
            env={
                **os.environ,
                "PGDATABASE": __import__(
                    "django.conf", fromlist=["settings"]
                ).settings.DATABASES["default"]["NAME"],
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        turn.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual(turn.attempt.state, "succeeded", turn.attempt.error)
        self.assertIn("离线演示", turn.reply)
        self.assertEqual(c.version, 2)
        task = confirm(user, c.pk, {"version": 2, "request_key": str(uuid.uuid4())})
        self.assertEqual(task.status, "pending")
        self.assertEqual(Attempt.objects.filter(task__kind="task").count(), 0)
