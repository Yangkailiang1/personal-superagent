import uuid
from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from personal_superagent.devices.auth import pair, new_pairing
from personal_superagent.intake.models import Conversation
from personal_superagent.collaboration.tests import PLAN, POLICY
from personal_superagent.collaboration.plans import publish
from personal_superagent.collaboration.routing import dispatch_pending
from personal_superagent.happier.services import control
from personal_superagent.execution.claims import claim_next
from personal_superagent.execution.models import Attempt
from .services import hello, claim, files_for, file_poll
from .models import LocalFile


class ModelingTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("model-owner")
        self.device, self.token = pair(new_pairing(self.user), "Blender computer")
        self.cfg = {
            "provider_fingerprint": "a" * 64,
            "model": "test",
            "addon_hash": "b" * 64,
            "protocol": 15,
            "grant_id": str(uuid.uuid4()),
        }
        hello(self.device, {"config": self.cfg})
        self.c = Conversation.objects.create(
            owner=self.user,
            plan_mode=True,
            draft={
                **PLAN,
                "steps": [
                    {
                        **PLAN["steps"][0],
                        "role": "modeler",
                        "tools": ["blender_modeling"],
                        "required_capabilities": ["blender.modeling"],
                    }
                ],
            },
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
        self.job = claim(self.device)["job"]
        self.a = Attempt.objects.get(pk=self.job["id"])

    def send(self, action, **data):
        return control(self.device, {**self.job, "action": action, **data})

    def report(self):
        return {
            "state": "succeeded",
            "text": "local delivery",
            "local_files": [
                {
                    "path": p,
                    "media_type": "application/octet-stream",
                    "size": 20,
                    "sha256": "a" * 64,
                }
                for p in ["model.blend", "preview.png"]
            ],
        }

    def test_capability_route_and_metadata_only(self):
        self.assertEqual(self.a.executor_kind, "blender")
        self.assertIsNone(claim_next(uuid.uuid4()))
        self.send("result", report=self.report())
        self.send("result", report=self.report())
        self.a.refresh_from_db()
        self.assertEqual(self.a.state, "succeeded")
        self.assertEqual(LocalFile.objects.count(), 2)
        self.assertNotIn("content", files_for(self.a)[0])
        file_poll(
            self.device,
            {"files": [{"id": str(LocalFile.objects.first().pk), "state": "missing"}]},
        )
        self.assertTrue(LocalFile.objects.filter(state="missing").exists())

    def test_reject_raw_content_and_cross_device(self):
        from django.http import Http404

        with self.assertRaises(ValueError):
            self.send(
                "result",
                report={
                    **self.report(),
                    "files": [{"path": "model.blend", "content": "raw bytes"}],
                },
            )
        other = get_user_model().objects.create_user("other-model-owner")
        device, _ = pair(new_pairing(other), "other")
        with self.assertRaises(Http404):
            control(device, {**self.job, "action": "heartbeat"})

    def test_missing_delivery_rejected_atomically(self):
        with self.assertRaises(ValueError):
            self.send("result", report={"state": "succeeded", "text": "claim"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.state, "running")
        self.assertEqual(LocalFile.objects.count(), 0)
