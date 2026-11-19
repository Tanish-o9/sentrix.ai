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

        # Prohibited command security check
        blocked, msg = run_sandbox_tests(".", command=["rm", "-rf", "/"])
        self.assertFalse(blocked)
        self.assertIn("Sandbox violation", msg)

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

    def test_repo_tree_and_file_inspector(self):
        # 1. Test Tree endpoint
        res = self.client.get("/api/repo/tree/?repo_url=")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["total_files"] > 0)
        self.assertTrue(len(data["files"]) > 0)

        # 2. Test File read endpoint
        first_file = data["files"][0]["path"]
        f_res = self.client.get(f"/api/repo/file/?repo_url=&path={first_file}")
        self.assertEqual(f_res.status_code, 200)
        self.assertIn("content", f_res.json())

    def test_repo_direct_commit_and_pr(self):
        res = self.client.post(
            "/api/repo/commit-pr/",
            data=json.dumps({
                "repo_url": "https://github.com/sentrix-org/test-repo",
                "path": "sentrix_backend/views.py",
                "content": "# test edit\n",
                "message": "test: web commit"
            }),
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")
        self.assertTrue("branch" in res.json())

    def test_settings_api_key_and_status(self):
        # 1. Invalid method
        get_res = self.client.get("/api/settings/api-key/")
        self.assertEqual(get_res.status_code, 405)

        # 2. Empty payload -> 400
        empty_res = self.client.post(
            "/api/settings/api-key/",
            data=json.dumps({"provider": "gemini", "api_key": "", "github_token": ""}),
            content_type="application/json"
        )
        self.assertEqual(empty_res.status_code, 400)

        # 3. Valid key and token save
        save_res = self.client.post(
            "/api/settings/api-key/",
            data=json.dumps({"provider": "gemini", "api_key": "test-key-123", "github_token": "ghp_testtoken"}),
            content_type="application/json"
        )
        self.assertEqual(save_res.status_code, 200)

        # 4. Status endpoint
        status_res = self.client.get("/api/settings/api-status/")
        self.assertEqual(status_res.status_code, 200)
        st_data = status_res.json()
        self.assertTrue(st_data["has_key"])
        self.assertTrue(st_data["has_github"])

    def test_project_list_and_create(self):
        # Create
        c_res = self.client.post(
            "/api/projects/",
            data=json.dumps({"name": "New Test Project", "repo_url": "https://github.com/test/repo"}),
            content_type="application/json"
        )
        self.assertEqual(c_res.status_code, 201)
        # List
        l_res = self.client.get("/api/projects/")
        self.assertEqual(l_res.status_code, 200)
        self.assertTrue(any(p["name"] == "New Test Project" for p in l_res.json()["projects"]))

    def test_task_detail_and_errors(self):
        # Create task
        t_res = self.client.post(
            "/api/tasks/",
            data=json.dumps({"project_id": self.project.id, "prompt": "Task for detail test"}),
            content_type="application/json"
        )
        tid = t_res.json()["id"]

        # Detail valid
        d_res = self.client.get(f"/api/tasks/{tid}/")
        self.assertEqual(d_res.status_code, 200)
        self.assertEqual(d_res.json()["id"], tid)
        self.assertIn("fork_url", d_res.json())

        # Detail invalid
        d404 = self.client.get("/api/tasks/999999/")
        self.assertEqual(d404.status_code, 404)

    def test_approval_hash_mismatch_and_rejection(self):
        # Create and run
        t_res = self.client.post(
            "/api/tasks/",
            data=json.dumps({"project_id": self.project.id, "prompt": "Implement status check"}),
            content_type="application/json"
        )
        tid = t_res.json()["id"]
        self.client.post(f"/api/tasks/{tid}/run/")

        # Hash mismatch -> 400
        bad_app = self.client.post(
            f"/api/tasks/{tid}/approve/",
            data=json.dumps({"patch_hash": "wrong_hash_12345", "decision": "APPROVED"}),
            content_type="application/json"
        )
        self.assertEqual(bad_app.status_code, 400)
        self.assertIn("Patch hash mismatch", bad_app.json()["error"])

        # Rejection -> status REJECTED
        rej_app = self.client.post(
            f"/api/tasks/{tid}/approve/",
            data=json.dumps({"decision": "REJECTED"}),
            content_type="application/json"
        )
        self.assertEqual(rej_app.status_code, 200)
        self.assertEqual(rej_app.json()["status"], "REJECTED")

        # Invalid 404 & 405
        self.assertEqual(self.client.get(f"/api/tasks/{tid}/approve/").status_code, 405)
        self.assertEqual(self.client.post("/api/tasks/999999/approve/", data="{}", content_type="application/json").status_code, 404)

    def test_update_patch_diff_errors(self):
        # 405 on GET
        self.assertEqual(self.client.get("/api/tasks/1/update-diff/").status_code, 405)
        # 404 on missing
        self.assertEqual(self.client.post("/api/tasks/999999/update-diff/", data=json.dumps({"diff": "abc"}), content_type="application/json").status_code, 404)

    def test_download_patch_errors(self):
        # 404 on missing task
        self.assertEqual(self.client.get("/api/tasks/999999/download-patch/").status_code, 404)

    def test_github_webhook_bot(self):
        # 1. Mentioning @sentrix
        hook_res = self.client.post(
            "/api/webhooks/github/",
            data=json.dumps({
                "comment": {"body": "Hey @sentrix please add rate limiting middleware"},
                "repository": {"html_url": "https://github.com/sentrix-org/test-repo"}
            }),
            content_type="application/json"
        )
        self.assertEqual(hook_res.status_code, 201)
        self.assertEqual(hook_res.json()["status"], "dispatched")

        # 2. Ignored when no mention
        ign_res = self.client.post(
            "/api/webhooks/github/",
            data=json.dumps({
                "comment": {"body": "Just a normal comment without bot mention"},
            }),
            content_type="application/json"
        )
        self.assertEqual(ign_res.status_code, 200)
        self.assertEqual(ign_res.json()["status"], "ignored")

        # 3. Invalid method
        self.assertEqual(self.client.get("/api/webhooks/github/").status_code, 405)

    def test_path_traversal_protection(self):
        # Path traversal read
        bad_get = self.client.get("/api/repo/file/?repo_url=&path=../../../../etc/passwd")
        self.assertEqual(bad_get.status_code, 403)
        self.assertEqual(bad_get.json()["error"], "Path traversal blocked")

        # Path traversal write
        bad_post = self.client.post(
            "/api/repo/file/",
            data=json.dumps({"repo_url": "", "path": "../../test_evil.txt", "content": "evil"}),
            content_type="application/json"
        )
        self.assertEqual(bad_post.status_code, 403)

    def test_target_file_heuristics(self):
        from sentrix_agno.workflow import get_target_file
        files = ["frontend/index.html", "backend/server.js", "sentrix_backend/views.py", "style.css"]
        self.assertEqual(get_target_file(files, "improve dashboard UI"), "frontend/index.html")
        self.assertEqual(get_target_file(files, "improve deshboard web"), "frontend/index.html")
        self.assertEqual(get_target_file(files, "add API server route"), "backend/server.js")
        self.assertEqual(get_target_file(files, "add MIT license"), "LICENSE")
        self.assertEqual(get_target_file(files, "update readme docs"), "README.md")
