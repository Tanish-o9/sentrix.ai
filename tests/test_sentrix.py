import json
from django.test import TestCase, Client
from sentrix_backend.models import Project, Task
from sentrix_backend.services import scan_repo_ast, run_sandbox_tests, create_github_draft_pr


class SentrixFullFeaturesTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.project = Project.objects.create(name="Demo Project", repo_url="https://github.com/sentrix-org/test-repo")

    def test_dashboard_renders(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"SENTRIX", res.content)

    def test_ast_repo_scanner(self):
        ast_data = scan_repo_ast(".")
        self.assertIsInstance(ast_data, dict)
        self.assertTrue(len(ast_data) > 0)

    def test_sandbox_runner(self):
        passed, out = run_sandbox_tests(".", command=["python", "-c", "print('hello from sandbox')"])
        self.assertTrue(passed)
        self.assertIn("hello from sandbox", out)

    def test_github_draft_pr_service(self):
        pr = create_github_draft_pr("sentrix-org/test-repo", "sentrix/task-1", "Test PR", "Test body")
        self.assertEqual(pr["state"], "draft")
        self.assertIn("pull", pr["html_url"])

    def test_complete_end_to_end_flow_with_pr(self):
        # 1. Create task
        res = self.client.post(
            "/api/tasks/",
            data=json.dumps({"project_id": self.project.id, "prompt": "Fix rate limiter token leak"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        task_id = res.json()["id"]

        # 2. Run Agno pipeline (includes AST scan & QA hook)
        run_res = self.client.post(f"/api/tasks/{task_id}/run/")
        self.assertEqual(run_res.status_code, 200)
        patch_hash = run_res.json()["patch_hash"]

        # 3. Approve and verify GitHub Draft PR URL created
        app_res = self.client.post(
            f"/api/tasks/{task_id}/approve/",
            data=json.dumps({"patch_hash": patch_hash, "decision": "APPROVED"}),
            content_type="application/json",
        )
        self.assertEqual(app_res.status_code, 200)
        self.assertIn("github.com/sentrix-org/test-repo/pull", app_res.json()["pr_url"])
