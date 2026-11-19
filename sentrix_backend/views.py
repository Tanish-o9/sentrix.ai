"""Django API Views & Dashboard for SENTRIX.ai.

Clean, minimal REST endpoints for task lifecycle, Agno agent execution,
multi-file patch editing, GitHub PR creation, webhooks, and the visual dashboard.
"""

import json
import os
import re
from pathlib import Path
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from sentrix_agno.workflow import run_aether_pipeline as run_sentrix_pipeline
from .models import Project, Task, TaskStep, CodePatch, Approval
from .services import calculate_patch_hash, scan_repo_ast, run_sandbox_tests, deploy_approved_patch, prepare_workspace

BASE_DIR = Path(__file__).resolve().parent.parent


def dashboard_view(request: HttpRequest):
    """Renders the SENTRIX.ai visual dashboard."""
    return render(request, "dashboard.html")


def ast_view(request: HttpRequest):
    """Returns AST symbols for repository intelligence."""
    repo_url = request.GET.get("repo_url", "")
    ok, path, msg = prepare_workspace(repo_url)
    return JsonResponse({"workspace": path, "message": msg, "symbols": scan_repo_ast(path)})


@csrf_exempt
def set_api_key(request: HttpRequest):
    """Saves LLM API key & GitHub Token in environment and persists to .env."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    data = json.loads(request.body)
    provider = data.get("provider", "gemini").lower()
    api_key = data.get("api_key", "").strip()
    github_token = data.get("github_token", "").strip()

    env_path = BASE_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    if api_key:
        key_var = f"{provider.upper()}_API_KEY"
        os.environ[key_var] = api_key
        os.environ["LLM_PROVIDER"] = provider
        lines = [l for l in lines if not l.startswith(f"{key_var}=") and not l.startswith("LLM_PROVIDER=")]
        lines.extend([f"{key_var}={api_key}", f"LLM_PROVIDER={provider}"])

    if github_token:
        os.environ["GITHUB_TOKEN"] = github_token
        lines = [l for l in lines if not l.startswith("GITHUB_TOKEN=")]
        lines.append(f"GITHUB_TOKEN={github_token}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return JsonResponse({"status": "ok", "message": "Settings updated and saved successfully!"})


def get_api_status(request: HttpRequest):
    """Returns active LLM provider and GitHub token status."""
    active_prov = (os.getenv("LLM_PROVIDER") or "").lower()
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_groq = bool(os.getenv("GROQ_API_KEY")) and active_prov == "groq"
    has_key = has_gemini or has_openai or has_groq
    has_github = bool(os.getenv("GITHUB_TOKEN"))
    provider_name = active_prov.capitalize() if has_key else "Offline"
    return JsonResponse({"has_key": has_key, "provider": provider_name, "has_github": has_github})


@csrf_exempt
def project_list_create(request: HttpRequest):
    if request.method == "POST":
        data = json.loads(request.body)
        project = Project.objects.create(name=data.get("name", "Default Project"), repo_url=data.get("repo_url", ""))
        return JsonResponse({"id": project.id, "name": project.name, "repo_url": project.repo_url}, status=201)

    projects = list(Project.objects.values("id", "name", "repo_url", "created_at"))
    return JsonResponse({"projects": projects})


@csrf_exempt
def task_list_create(request: HttpRequest):
    if request.method == "POST":
        data = json.loads(request.body)
        repo_url = data.get("repo_url", "").strip()
        prompt = data.get("prompt", "").strip()
        project_id = data.get("project_id")

        if project_id:
            project = Project.objects.get(id=project_id)
        else:
            project_name = repo_url.split("/")[-1] if "/" in repo_url else "Local Workspace"
            project, _ = Project.objects.get_or_create(repo_url=repo_url, defaults={"name": project_name})

        task = Task.objects.create(project=project, prompt=prompt)
        return JsonResponse({"id": task.id, "prompt": task.prompt, "repo_url": project.repo_url, "status": task.status}, status=201)

    tasks = []
    for t in Task.objects.select_related("project").order_by("-id"):
        tasks.append({
            "id": t.id,
            "project_id": t.project_id,
            "repo_url": t.project.repo_url,
            "prompt": t.prompt,
            "status": t.status,
            "pr_url": t.pr_url,
            "created_at": t.created_at,
        })
    return JsonResponse({"tasks": tasks})


@csrf_exempt
def run_task(request: HttpRequest, task_id: int):
    """Executes the Agno Agent pipeline with real workspace preparation, AST scanning & bounded QA repair."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        task = Task.objects.select_related("project").get(id=task_id)
    except Task.DoesNotExist:
        return JsonResponse({"error": "Task not found"}, status=404)

    task.status = Task.Status.PLANNING
    task.save()

    # 1. Prepare Workspace
    repo_url = task.project.repo_url
    ok, workspace_path, status_msg = prepare_workspace(repo_url)

    # 2. Repository Multi-Language Scanner
    ast_summary = scan_repo_ast(workspace_path)
    repo_context = json.dumps(ast_summary)

    # 3. Optional runtime API key
    body = {}
    try:
        body = json.loads(request.body) if request.body else {}
    except Exception:
        pass
    api_key = body.get("api_key")
    provider = body.get("provider")

    # 4. Invoke Agno Multi-Agent Pipeline
    agent_output = run_sentrix_pipeline(
        task_prompt=task.prompt,
        repo_context=repo_context,
        test_runner_fn=lambda diff: run_sandbox_tests(workspace_path),
        api_key=api_key,
        provider=provider,
        workspace_path=workspace_path,
    )

    # 5. Save Steps for Live Progress
    task.plan = agent_output["plan"]
    TaskStep.objects.create(task=task, agent_name="Workspace Service", step_type="WORKSPACE", output_summary=f"Cloned repository and scanned {len(ast_summary)} files.")
    TaskStep.objects.create(task=task, agent_name="Agno Planner", step_type="PLANNING", output_summary=f"Formulated acceptance criteria targeting: {', '.join(agent_output['plan'].get('files_to_inspect', []))}")
    TaskStep.objects.create(task=task, agent_name="Agno Developer", step_type="CODING", output_summary=agent_output["patch"]["explanation"])
    TaskStep.objects.create(task=task, agent_name="Agno QA Agent", step_type="TEST_GENERATION", output_summary="Generated automated verification test suite.")
    if agent_output.get("qa_retries", 0) > 0:
        TaskStep.objects.create(task=task, agent_name="Agno Debugger", step_type="REPAIR", output_summary=f"Self-healed after {agent_output['qa_retries']} retries.")
    TaskStep.objects.create(task=task, agent_name="Agno Reviewer", step_type="AUDIT", output_summary=str(agent_output["review"].get("reviewer_comments", "Passed")))

    # 6. Save Patch with Cryptographic SHA256 Hash
    diff_text = agent_output["patch"].get("diff", "")
    if diff_text and ("--- " in diff_text or "diff --git" in diff_text):
        patch_hash = calculate_patch_hash(diff_text)
        CodePatch.objects.update_or_create(
            task=task,
            defaults={"patch_hash": patch_hash, "diff": diff_text, "explanation": agent_output["patch"]["explanation"]},
        )
        task.status = Task.Status.AWAITING_APPROVAL
    else:
        patch_hash = ""
        CodePatch.objects.update_or_create(
            task=task,
            defaults={"patch_hash": "", "diff": "", "explanation": agent_output["patch"]["explanation"]},
        )
        task.status = Task.Status.APPROVED
    task.save()

    steps = list(task.steps.values("agent_name", "step_type", "output_summary", "created_at"))
    return JsonResponse({
        "task_id": task.id,
        "status": task.status,
        "plan": task.plan,
        "patch": agent_output["patch"],
        "patch_hash": patch_hash,
        "review": agent_output["review"],
        "qa_retries": agent_output.get("qa_retries", 0),
        "workspace_msg": status_msg,
        "is_info": agent_output.get("is_info", False),
        "llm_error": agent_output.get("llm_error"),
        "model_used": agent_output.get("model_used", "none"),
        "steps": steps,
    })


def task_detail(request: HttpRequest, task_id: int):
    """Returns task status, steps, and patch info."""
    try:
        task = Task.objects.select_related("project").get(id=task_id)
    except Task.DoesNotExist:
        return JsonResponse({"error": "Task not found"}, status=404)

    patch_data = None
    if hasattr(task, "patch"):
        patch_data = {"patch_hash": task.patch.patch_hash, "diff": task.patch.diff, "explanation": task.patch.explanation}

    clean_url = (task.project.repo_url or "").strip().rstrip("/")
    parts = clean_url.split("github.com/")[-1].split("/")
    owner, repo_name = (parts[0], parts[1].replace(".git", "")) if len(parts) >= 2 else ("owner", "repo")
    fork_url = f"https://github.com/{owner}/{repo_name}/fork" if "github.com" in clean_url else ""
    branch_name = f"sentrix/task-{task.id}"

    steps = list(task.steps.values("agent_name", "step_type", "output_summary", "created_at"))
    return JsonResponse({
        "id": task.id,
        "prompt": task.prompt,
        "repo_url": task.project.repo_url,
        "status": task.status,
        "plan": task.plan,
        "pr_url": task.pr_url,
        "patch": patch_data,
        "steps": steps,
        "fork_url": fork_url,
        "branch": branch_name,
    })


@csrf_exempt
def update_patch_diff(request: HttpRequest, task_id: int):
    """Allows human reviewer to edit the patch inline before approval."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    data = json.loads(request.body)
    new_diff = data.get("diff", "").strip()

    try:
        task = Task.objects.get(id=task_id)
        if not hasattr(task, "patch"):
            return JsonResponse({"error": "No patch to update"}, status=400)
        new_hash = calculate_patch_hash(new_diff)
        task.patch.diff = new_diff
        task.patch.patch_hash = new_hash
        task.patch.save()
        return JsonResponse({"status": "ok", "patch_hash": new_hash, "diff": new_diff})
    except Task.DoesNotExist:
        return JsonResponse({"error": "Task not found"}, status=404)


def download_patch(request: HttpRequest, task_id: int):
    """Downloads the generated patch file directly."""
    try:
        task = Task.objects.get(id=task_id)
        if not hasattr(task, "patch") or not task.patch.diff:
            return HttpResponse("No patch available for this task.", status=404)
        response = HttpResponse(task.patch.diff, content_type="text/x-diff")
        response["Content-Disposition"] = f'attachment; filename="sentrix_task_{task.id}.patch"'
        return response
    except Task.DoesNotExist:
        return HttpResponse("Task not found", status=404)


@csrf_exempt
def approve_task(request: HttpRequest, task_id: int):
    """Enforces human-in-the-loop approval and safely deploys to branch/PR."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    data = json.loads(request.body)
    submitted_hash = data.get("patch_hash")
    decision = data.get("decision", "APPROVED").upper()

    try:
        task = Task.objects.select_related("project").get(id=task_id)
    except Task.DoesNotExist:
        return JsonResponse({"error": "Task not found"}, status=404)

    if hasattr(task, "patch") and task.patch.diff and task.patch.patch_hash != submitted_hash:
        return JsonResponse({"error": "Patch hash mismatch. Approval rejected."}, status=400)

    Approval.objects.create(task=task, patch_hash=submitted_hash or "", approver=data.get("approver", "human_reviewer"), decision=decision)

    notice = ""
    is_external = False
    fork_url = ""
    branch_name = f"sentrix/task-{task.id}"
    if decision == "APPROVED":
        task.status = Task.Status.APPROVED
        ok, workspace_path, _ = prepare_workspace(task.project.repo_url)
        github_token = os.getenv("GITHUB_TOKEN", "")
        deploy_info = deploy_approved_patch(
            workspace_path=workspace_path,
            repo_url=task.project.repo_url,
            task_id=task.id,
            prompt=task.prompt,
            diff_text=task.patch.diff if hasattr(task, "patch") else "",
            github_token=github_token,
        )
        task.pr_url = deploy_info.get("html_url", "")
        notice = deploy_info.get("notice", "")
        is_external = deploy_info.get("is_external", False)
        fork_url = deploy_info.get("fork_url", "")
        branch_name = deploy_info.get("branch", branch_name)
    else:
        task.status = Task.Status.REJECTED

    task.save()
    return JsonResponse({
        "task_id": task.id,
        "status": task.status,
        "patch_hash": submitted_hash,
        "decision": decision,
        "pr_url": task.pr_url,
        "notice": notice,
        "is_external": is_external,
        "fork_url": fork_url,
        "branch": branch_name,
    })


@csrf_exempt
def github_webhook(request: HttpRequest):
    """Automated GitHub Bot: triggers tasks from issue comments mentioning @sentrix."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
        body_text = data.get("comment", {}).get("body") or data.get("issue", {}).get("body", "")
        if "@sentrix" not in body_text.lower():
            return JsonResponse({"status": "ignored", "message": "No @sentrix mention found."})

        prompt = re.sub(r"@sentrix(?:\.ai)?", "", body_text, flags=re.I).strip()
        repo_url = data.get("repository", {}).get("html_url", "https://github.com/Tanish-o9/sentrix.ai")
        project, _ = Project.objects.get_or_create(repo_url=repo_url, defaults={"name": repo_url.split('/')[-1]})
        task = Task.objects.create(project=project, prompt=prompt)
        return JsonResponse({"status": "dispatched", "task_id": task.id, "prompt": prompt, "repo_url": repo_url}, status=201)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


def repo_tree_view(request: HttpRequest):
    """Returns directory and file hierarchy for any repository workspace."""
    repo_url = request.GET.get("repo_url", "").strip()
    ok, workspace_path, msg = prepare_workspace(repo_url)
    if not ok:
        return JsonResponse({"error": msg}, status=400)

    path = Path(workspace_path).resolve()
    SKIP = (".git", ".venv", "venv", "__pycache__", "node_modules", "workspaces", "dist", "build")
    files_list = []

    for p in sorted(path.rglob("*")):
        if p.is_file():
            rel_parts = p.relative_to(path).parts
            if any(skip in rel_parts for skip in SKIP):
                continue
            parent_dir = p.parent.relative_to(path).as_posix()
            files_list.append({
                "path": p.relative_to(path).as_posix(),
                "name": p.name,
                "dir": "" if parent_dir == "." else parent_dir,
                "size": p.stat().st_size,
                "ext": p.suffix.lower(),
            })

    return JsonResponse({
        "workspace": str(path),
        "repo_url": repo_url,
        "total_files": len(files_list),
        "files": files_list,
    })


@csrf_exempt
def repo_file_view(request: HttpRequest):
    """Reads or updates a specific file within a repository workspace."""
    if request.method == "GET":
        repo_url = request.GET.get("repo_url", "").strip()
        rel_file = request.GET.get("path", "").strip().lstrip("/\\")
        ok, ws, msg = prepare_workspace(repo_url)
        target = (Path(ws) / rel_file).resolve()
        if not str(target).startswith(str(Path(ws).resolve())):
            return JsonResponse({"error": "Path traversal blocked"}, status=403)
        if not target.exists() or not target.is_file():
            return JsonResponse({"error": "File not found"}, status=404)
        content = target.read_text(encoding="utf-8", errors="ignore")
        return JsonResponse({"path": rel_file, "content": content, "size": target.stat().st_size})

    if request.method == "POST":
        data = json.loads(request.body)
        repo_url = data.get("repo_url", "").strip()
        rel_file = data.get("path", "").strip().lstrip("/\\")
        content = data.get("content", "")
        ok, ws, msg = prepare_workspace(repo_url)
        target = (Path(ws) / rel_file).resolve()
        if not str(target).startswith(str(Path(ws).resolve())):
            return JsonResponse({"error": "Path traversal blocked"}, status=403)
        target.write_text(content, encoding="utf-8")
        return JsonResponse({"status": "saved", "path": rel_file, "size": len(content.encode("utf-8"))})


@csrf_exempt
def repo_direct_commit_pr(request: HttpRequest):
    """Directly commits in-browser file changes to a new branch and opens a GitHub PR / Fork."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    data = json.loads(request.body)
    repo_url = data.get("repo_url", "").strip()
    rel_file = data.get("path", "").strip().lstrip("/\\")
    content = data.get("content", "")
    commit_msg = data.get("message", f"Update {rel_file} via SENTRIX web editor").strip()

    ok, ws, msg = prepare_workspace(repo_url)
    ws_path = Path(ws).resolve()
    target = (ws_path / rel_file).resolve()
    if not str(target).startswith(str(ws_path)):
        return JsonResponse({"error": "Path traversal blocked"}, status=403)

    project_name = repo_url.split("/")[-1] if "/" in repo_url else "Workspace"
    project, _ = Project.objects.get_or_create(repo_url=repo_url, defaults={"name": project_name})
    task = Task.objects.create(project=project, prompt=commit_msg, status=Task.Status.APPROVED)

    deploy_info = deploy_approved_patch(
        workspace_path=str(ws_path),
        repo_url=repo_url,
        task_id=task.id,
        prompt=commit_msg,
        write_files={rel_file: content},
        github_token=os.getenv("GITHUB_TOKEN", ""),
    )
    task.pr_url = deploy_info.get("html_url", "")
    task.save()

    return JsonResponse({
        "status": "ok",
        "task_id": task.id,
        "branch": deploy_info.get("branch", f"sentrix/task-{task.id}"),
        "pr_url": deploy_info.get("html_url", ""),
        "fork_url": deploy_info.get("fork_url", ""),
        "is_external": deploy_info.get("is_external", False),
        "notice": deploy_info.get("notice", ""),
    })
