import json
from django.test import TestCase, Client
from sentrix_backend.models import Project, Task
from sentrix_backend.services import scan_repo_ast, run_sandbox_tests, deploy_approved_patch


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

    def test_github_deploy_service(self):
        deploy_info = deploy_approved_patch(".", "https://github.com/sentrix-org/test-repo", 1, "Test PR", "")
        self.assertIn("html_url", deploy_info)
        self.assertIn("github.com/sentrix-org/test-repo", deploy_info["html_url"])
        self.assertEqual(deploy_info["state"], "approved")

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
        self.assertTrue(len(patch_hash) > 0)

        # 3. Approve and verify GitHub compare/PR URL created
        app_res = self.client.post(
            f"/api/tasks/{task_id}/approve/",
            data=json.dumps({"patch_hash": patch_hash, "decision": "APPROVED"}),
            content_type="application/json",
        )
        self.assertEqual(app_res.status_code, 200)
        self.assertIn("github.com/sentrix-org/test-repo", app_res.json()["pr_url"])

    def test_exploration_query_handling(self):
        # Queries like "show me all files" should NOT produce fake diffs
        res = self.client.post(
            "/api/tasks/",
            data=json.dumps({"project_id": self.project.id, "prompt": "show me all files of this repo"}),
            content_type="application/json",
        )
        task_id = res.json()["id"]
        run_res = self.client.post(f"/api/tasks/{task_id}/run/")
        self.assertEqual(run_res.status_code, 200)
        data = run_res.json()
        self.assertEqual(data["patch"]["diff"], "")
        self.assertEqual(data["patch_hash"], "")
        self.assertEqual(data["status"], "APPROVED")
        self.assertIn("Repository exploration complete", data["patch"]["explanation"])

    def test_inline_patch_editing_and_rehash(self):
        res = self.client.post(
            "/api/tasks/",
            data=json.dumps({"project_id": self.project.id, "prompt": "Add health endpoint"}),
            content_type="application/json",
        )
        task_id = res.json()["id"]
        self.client.post(f"/api/tasks/{task_id}/run/")

        # Edit the diff inline
        new_diff = "diff --git a/test.py b/test.py\n--- a/test.py\n+++ b/test.py\n@@ -1,1 +1,2 @@\n# old\n+# new feature\n"
        up_res = self.client.post(
            f"/api/tasks/{task_id}/update-diff/",
            data=json.dumps({"diff": new_diff}),
            content_type="application/json",
        )
        self.assertEqual(up_res.status_code, 200)
        self.assertEqual(up_res.json()["status"], "ok")
        self.assertTrue(len(up_res.json()["patch_hash"]) > 0)

        # Download patch file
        dl_res = self.client.get(f"/api/tasks/{task_id}/download-patch/")
        self.assertEqual(dl_res.status_code, 200)
        self.assertEqual(dl_res["Content-Type"], "text/x-diff")
        self.assertIn(b"# new feature", dl_res.content)
