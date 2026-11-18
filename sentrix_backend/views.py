"""Django API Views & Dashboard for SENTRIX.ai.

Clean, minimal REST endpoints for task lifecycle, Agno agent execution,
sandbox testing, GitHub PR creation, and the visual Human Approval dashboard.
"""

import json
import os
from django.http import JsonResponse, HttpRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from sentrix_agno.workflow import run_aether_pipeline as run_sentrix_pipeline
from .models import Project, Task, TaskStep, CodePatch, Approval
from .services import calculate_patch_hash, scan_repo_ast, run_sandbox_tests, create_github_draft_pr, prepare_workspace


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
    """Saves LLM API key in current environment for Agno agents."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    data = json.loads(request.body)
    provider = data.get("provider", "openai").upper()
    api_key = data.get("api_key", "").strip()
    if api_key:
        os.environ[f"{provider}_API_KEY"] = api_key
        os.environ["LLM_PROVIDER"] = provider.lower()
        return JsonResponse({"status": "ok", "message": f"{provider} API key configured successfully!"})
    return JsonResponse({"error": "API key cannot be empty"}, status=400)


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

    # 1. Prepare Workspace (Clone if remote GitHub repo)
    repo_url = task.project.repo_url
    ok, workspace_path, status_msg = prepare_workspace(repo_url)

    # 2. Repository AST Scanner
    ast_summary = scan_repo_ast(workspace_path)
    repo_context = json.dumps(ast_summary)

    # 3. Optional runtime API key from request
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
    )

    # 5. Save Plan and Task Steps in Django DB
    task.plan = agent_output["plan"]
    TaskStep.objects.create(task=task, agent_name="Workspace Service", step_type="WORKSPACE", output_summary=status_msg)
    TaskStep.objects.create(task=task, agent_name="Agno Planner", step_type="PLANNING", output_summary=str(agent_output["plan"]))
    TaskStep.objects.create(task=task, agent_name="Agno Developer", step_type="CODING", output_summary=agent_output["patch"]["explanation"])
    if agent_output.get("qa_retries", 0) > 0:
        TaskStep.objects.create(task=task, agent_name="Agno Debugger", step_type="REPAIR", output_summary=f"Repaired after {agent_output['qa_retries']} retries.")
    TaskStep.objects.create(task=task, agent_name="Agno Reviewer", step_type="AUDIT", output_summary=str(agent_output["review"]))

    # 6. Save Patch with Cryptographic SHA256 Hash
    diff_text = agent_output["patch"]["diff"]
    patch_hash = calculate_patch_hash(diff_text)
    CodePatch.objects.update_or_create(
        task=task,
        defaults={"patch_hash": patch_hash, "diff": diff_text, "explanation": agent_output["patch"]["explanation"]},
    )

    # 7. Await Human Approval
    task.status = Task.Status.AWAITING_APPROVAL
    task.save()

    return JsonResponse({
        "task_id": task.id,
        "status": task.status,
        "plan": task.plan,
        "patch_hash": patch_hash,
        "review": agent_output["review"],
        "qa_retries": agent_output.get("qa_retries", 0),
        "workspace_msg": status_msg,
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
    })


@csrf_exempt
def approve_task(request: HttpRequest, task_id: int):
    """Enforces human-in-the-loop approval and creates GitHub Draft PR upon approval."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    data = json.loads(request.body)
    submitted_hash = data.get("patch_hash")
    decision = data.get("decision", "APPROVED").upper()

    try:
        task = Task.objects.select_related("project").get(id=task_id)
    except Task.DoesNotExist:
        return JsonResponse({"error": "Task not found"}, status=404)

    if not hasattr(task, "patch") or task.patch.patch_hash != submitted_hash:
        return JsonResponse({"error": "Patch hash mismatch. Approval rejected."}, status=400)

    Approval.objects.create(task=task, patch_hash=submitted_hash, approver=data.get("approver", "human_reviewer"), decision=decision)

    if decision == "APPROVED":
        task.status = Task.Status.APPROVED
        pr_info = create_github_draft_pr(
            repo_url=task.project.repo_url,
            branch_name=f"sentrix/task-{task.id}",
            title=f"SENTRIX: {task.prompt[:50]}",
            body=f"Automated draft PR generated by SENTRIX.ai Agno agents for Task #{task.id}.\n\nApproved Patch Hash: `{submitted_hash}`",
        )
        task.pr_url = pr_info.get("html_url", "")
    else:
        task.status = Task.Status.REJECTED

    task.save()
    return JsonResponse({
        "task_id": task.id,
        "status": task.status,
        "patch_hash": submitted_hash,
        "decision": decision,
        "pr_url": task.pr_url,
    })
