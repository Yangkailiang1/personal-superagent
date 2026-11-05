from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Task


class TaskAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("alice", password="test-only-a-8437")
        cls.bob = get_user_model().objects.create_user("bob", password="test-only-b-3978")
        cls.foreign = Task.objects.create(owner=cls.bob, title="bob-private", description="secret")

    def test_anonymous_redirected_to_login(self):
        self.assertRedirects(self.client.get("/"), "/accounts/login/?next=/")

    def test_password_login_and_post_logout(self):
        response = self.client.post(reverse("login"), {"username": "alice", "password": "test-only-a-8437"})
        self.assertRedirects(response, "/app/", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_owner_and_status_are_not_client_controlled(self):
        self.client.force_login(self.alice)
        response = self.client.post("/api/create/", {
            "title": "alice task", "text": "整理资料",
            "owner": self.bob.pk, "status": "completed",
        }, content_type="application/json")
        task = Task.objects.get(owner=self.alice)
        self.assertEqual(task.status, Task.Status.PENDING)
        self.assertEqual(response.status_code, 201)

    def test_list_and_detail_isolated(self):
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get("/api/bootstrap/"), "bob-private")
        self.assertRedirects(self.client.get("/"), "/app/", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("task_detail", args=[self.foreign.pk])).status_code, 404)

    def test_invalid_task_not_saved(self):
        self.client.force_login(self.alice)
        response = self.client.post("/api/create/", {"text": ""}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Task.objects.filter(owner=self.alice).exists())

    def test_csrf_required_on_create_and_login(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.post(reverse("login"), {"username": "alice"}).status_code, 403)
        browser.force_login(self.alice)
        self.assertEqual(browser.post("/api/create/", {"text": "blocked"}, content_type="application/json").status_code, 403)
        # 模拟浏览器先取页面，再带上表单 token；正常请求不能被一并禁掉。
        browser.get("/api/bootstrap/")
        token = browser.cookies["csrftoken"].value
        response = browser.post("/api/create/", {"text": "normal"}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)

    def test_old_task_link_opens_same_task_in_new_workspace(self):
        self.client.force_login(self.alice)
        task = Task.objects.create(owner=self.alice, title="test", description="existing")
        self.assertRedirects(
            self.client.get(reverse("task_detail", args=[task.pk])),
            f"/app/?task={task.pk}", fetch_redirect_response=False,
        )
        self.assertEqual(self.client.post("/", {"title": "old form"}).status_code, 405)
