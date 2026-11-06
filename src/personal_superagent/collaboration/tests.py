import json
import uuid
import os
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from personal_superagent.intake.models import Conversation
from personal_superagent.execution.lifecycle import StateConflict
from personal_superagent.execution.models import Attempt
from .models import Source, Page, Proposal, Schedule, Inspection
from .plans import publish
from .routing import provision, dispatch_pending, candidates
from .schema import Plan

PLAN = {
    "title": "学习计划",
    "goal": "整理材料",
    "materials": "用户材料",
    "deliverables": ["文档"],
    "acceptance": ["明确来源"],
    "questions": [],
    "assumptions": [],
    "device_needs": "仅云端",
    "steps": [
        {
            "key": "write",
            "title": "整理",
            "goal": "整理材料",
            "role": "writer",
            "tools": ["inspect_context"],
            "depends_on": [],
            "deliverables": ["文档"],
            "acceptance": ["覆盖目标"],
        },
        {
            "key": "review",
            "title": "检查",
            "goal": "检查前序内容",
            "role": "reviewer",
            "tools": ["inspect_context"],
            "depends_on": ["write"],
            "deliverables": ["检查说明"],
            "acceptance": ["列出问题"],
        },
    ],
}
POLICY = {"mode": "demo", "max_model_calls": 24, "max_images": 0, "timeout": 1800}


class BusinessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("plan-owner")
        self.other = get_user_model().objects.create_user("plan-other")
        self.c = Conversation.objects.create(
            owner=self.user, plan_mode=True, draft=PLAN
        )
        provision(self.user)

    def test_publication_idempotent_dependencies_and_owner(self):
        d = {"version": 1, "request_key": str(uuid.uuid4()), "policy": POLICY}
        r = publish(self.user, self.c.pk, d)
        self.assertEqual(publish(self.user, self.c.pk, d), r)
        self.assertEqual(r.tasks.count(), 2)
        self.assertEqual(
            r.tasks.filter(dispatch__key="review").get().dependencies.count(), 1
        )
        self.assertFalse(r.tasks.exclude(status="pending").exists())
        from django.http import Http404

        with self.assertRaises(Http404):
            publish(self.other, self.c.pk, d)

    def test_cycle_rejected(self):
        from pydantic import ValidationError

        bad = {
            **PLAN,
            "steps": [{**PLAN["steps"][0], "depends_on": ["review"]}, PLAN["steps"][1]],
        }
        with self.assertRaises(ValidationError):
            Plan.model_validate(bad)

    def test_unauthorized_or_unconfigured_tools_rejected(self):
        self.c.draft = {
            **PLAN,
            "steps": [{**PLAN["steps"][0], "tools": ["generate_image"]}],
        }
        self.c.save()
        with self.assertRaises(ValueError):
            publish(
                self.user,
                self.c.pk,
                {"version": 1, "request_key": str(uuid.uuid4()), "policy": POLICY},
            )

    def test_dispatch_only_ready_dependency(self):
        r = publish(
            self.user,
            self.c.pk,
            {"version": 1, "request_key": str(uuid.uuid4()), "policy": POLICY},
        )
        dispatch_pending()
        self.assertEqual(
            Attempt.objects.filter(input_snapshot__kind="routing").count(), 1
        )
        self.assertEqual(r.tasks.filter(dispatch__key="review").get().routes.count(), 0)

    def test_historical_agent_not_cross_conversation(self):
        r = publish(
            self.user,
            self.c.pk,
            {"version": 1, "request_key": str(uuid.uuid4()), "policy": POLICY},
        )
        task = r.tasks.get(dispatch__key="write")
        self.assertTrue(candidates(task))
        self.assertTrue(all(a.owner_id == self.user.pk for a in candidates(task)))

    def test_budget_survives_reopen(self):
        from .budget import spend

        with TemporaryDirectory() as d:
            self.assertEqual(spend(d, "image", 1), 1)
            with self.assertRaises(ValueError):
                spend(d, "image", 1)

    def test_knowledge_revision_conflict_and_sources(self):
        from personal_superagent.knowledge.services import approve, query

        source = Source.objects.create(
            owner=self.user, title="材料", content="可靠的知识"
        )
        p = Proposal.objects.create(
            owner=self.user,
            state="review",
            report="整理",
            changes=[
                {
                    "slug": "notes",
                    "base": 0,
                    "content": "可靠的知识",
                    "sources": [str(source.pk)],
                }
            ],
        )
        approve(self.user, p.pk)
        approve(self.user, p.pk)
        self.assertEqual(Page.objects.get(owner=self.user).revision, 1)
        self.assertEqual(len(query(self.user, "知识")), 1)
        stale = Proposal.objects.create(
            owner=self.user, state="review", changes=p.changes
        )
        with self.assertRaises(StateConflict):
            approve(self.user, stale.pk)
        self.assertEqual(query(self.other, "知识"), [])

    def test_inspection_once_and_no_catchup(self):
        from personal_superagent.knowledge.services import schedule_due
        from datetime import datetime, timezone as tz

        Schedule.objects.create(owner=self.user, enabled=True, mode="demo")
        now = datetime(2026, 11, 8, 2, tzinfo=tz.utc)
        schedule_due(now)
        schedule_due(now)
        self.assertEqual(Inspection.objects.count(), 1)
        self.assertEqual(Inspection.objects.get().day.isoformat(), "2026-11-08")

    def test_choice_has_three_distinct_options_and_custom(self):
        from .schema import Choice

        self.assertEqual(
            len(Choice(prompt="选择", options=["甲", "乙", "丙"]).options), 3
        )
        with self.assertRaises(ValueError):
            Choice(prompt="选择", options=["甲", "甲", "丙"])


class GraphTests(TransactionTestCase):
    def test_main_choice_then_plan_runs_real_graph(self):
        from .conversation_agent import run

        first = json.loads(
            run(
                {"text": "整理学习材料", "draft": {}, "messages": [], "answers": []},
                "demo",
                lambda *a: None,
            )
        )
        self.assertEqual(len(first["question"]["options"]), 3)
        second = json.loads(
            run(
                {
                    "text": "清单",
                    "draft": {},
                    "messages": [],
                    "answers": [{"answer": "清单"}],
                },
                "demo",
                lambda *a: None,
            )
        )
        self.assertEqual(len(second["draft"]["steps"]), 2)

    def test_v06_checkpoint_approvals_and_budget(self):
        from personal_superagent.workflow_v06.checkpoints import (
            run_workflow,
            execution_config,
        )

        with TemporaryDirectory() as d:
            payload = {
                "attempt_id": str(uuid.uuid4()),
                "mode": "demo",
                "action": "start",
                "checkpoint_dir": d,
                "snapshot": {
                    "title": "整理",
                    "description": "材料",
                    "workflow": execution_config("demo"),
                    "device": None,
                    "dispatch": {"role": "writer", "tools": ["inspect_context"]},
                    "policy": POLICY,
                },
            }
            result = run_workflow(payload, lambda *a: None)
            self.assertTrue(result["pending"])
            self.assertTrue((Path(d) / "budget.sqlite3").exists())
            decisions = {}
            for p in result["pending"]:
                decisions.setdefault(p["interrupt_id"], {"decisions": []})[
                    "decisions"
                ].append({"type": "approve"})
            payload.update(action="resume", decisions=decisions)
            result = run_workflow(payload, lambda *a: None)
            self.assertTrue(result["complete"])


class ImageOwnershipTests(TestCase):
    def test_real_png_bytes_owner_and_traversal(self):
        import io, base64
        from PIL import Image
        from .assets import upload, project
        from personal_superagent.execution.models import Attempt
        from personal_superagent.collaboration.models import ImageAsset

        user = get_user_model().objects.create_user("image-owner")
        other = get_user_model().objects.create_user("image-other")
        from personal_superagent.tasks.models import Task

        task = Task.objects.create(owner=user, title="image", description="x")
        attempt = Attempt.objects.create(
            task=task, request_key=uuid.uuid4(), mode="demo", input_snapshot={}
        )
        out = io.BytesIO()
        Image.new("RGB", (2, 2)).save(out, "PNG")
        content = out.getvalue()
        name = uuid.uuid4().hex + ".png"
        with (
            TemporaryDirectory() as d,
            patch.dict(os.environ, {"AGENT_RUNTIME_DIR": d}),
        ):
            upload(attempt, name, base64.b64encode(content).decode())
            project(attempt, {"images": [{"name": name}]})
            asset = ImageAsset.objects.get(attempt=attempt)
            self.client.force_login(user)
            response = self.client.get(f"/api/images/{asset.pk}/")
            self.assertEqual(b"".join(response.streaming_content), content)
            self.client.force_login(other)
            self.assertEqual(
                self.client.get(f"/api/images/{asset.pk}/").status_code, 404
            )
            with self.assertRaises(ValueError):
                upload(attempt, "../secret.png", base64.b64encode(content).decode())


class NativeLocalFilesTests(TransactionTestCase):
    def test_local_graph_reads_and_writes_only_after_approval(self):
        from personal_superagent.workflow_v06.checkpoints import (
            run_workflow,
            execution_config,
        )
        from personal_superagent.client.files import describe_root
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            notes = root / "notes"
            notes.mkdir()
            (notes / "input.md").write_text("V06_LOCAL_FILE_SENTINEL")
            scope = {
                "grant_id": str(uuid.uuid4()),
                "device_id": str(uuid.uuid4()),
                "label": "测试笔记",
                "tools": ["list_files", "read_text", "write_text"],
                "source_path": "input.md",
            }
            grant = {
                **describe_root(str(notes)),
                "id": scope["grant_id"],
                "tools": scope["tools"],
            }
            authorizations = root / "grants.json"
            authorizations.write_text(json.dumps([grant]))
            payload = {
                "attempt_id": str(uuid.uuid4()),
                "mode": "demo",
                "action": "start",
                "checkpoint_dir": str(root / "run"),
                "local_root": grant,
                "local_authorizations": str(authorizations),
                "snapshot": {
                    "title": "读取并整理",
                    "description": "整理指定材料",
                    "workflow": execution_config("demo"),
                    "device": scope,
                    "dispatch": {
                        "role": "writer",
                        "tools": [
                            "local_read_text",
                            "local_list_files",
                            "local_write_text",
                        ],
                    },
                    "policy": POLICY,
                },
            }
            result = run_workflow(payload, lambda *a: None)
            self.assertTrue(result["pending"])
            self.assertFalse((notes / "superagent-result.md").exists())
            self.assertEqual(result["pending"][0]["action"]["name"], "local_write_text")
            for _ in range(3):
                decisions = {}
                for p in result["pending"]:
                    decisions.setdefault(p["interrupt_id"], {"decisions": []})[
                        "decisions"
                    ].append({"type": "approve"})
                payload.update(action="resume", decisions=decisions)
                result = run_workflow(payload, lambda *a: None)
                if result["complete"]:
                    break
            self.assertTrue(result["complete"])
            self.assertIn(
                "V06_LOCAL_FILE_SENTINEL", (notes / "superagent-result.md").read_text()
            )
