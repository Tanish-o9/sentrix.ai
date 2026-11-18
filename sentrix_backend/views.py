"""Django API Views & Dashboard for SENTRIX.ai.

Clean, minimal REST endpoints for task lifecycle, Agno agent execution,
sandbox testing, GitHub PR creation, and the visual Human Approval dashboard.
"""

import json
import os
from pathlib import Path
from django.http import JsonResponse, HttpRequest
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
    """Saves LLM API key in environment and persists to .env."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    data = json.loads(request.body)
    provider = data.get("provider", "gemini").lower()
    api_key = data.get("api_key", "").strip()
    if not api_key:
        return JsonResponse({"error": "API key cannot be empty"}, status=400)

    key_var = f"{provider.upper()}_API_KEY"
    os.environ[key_var] = api_key
    os.environ["LLM_PROVIDER"] = provider

    env_path = BASE_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    filtered = [l for l in lines if not l.startswith(f"{key_var}=") and not l.startswith("LLM_PROVIDER=")]
    filtered.extend([f"{key_var}={api_key}", f"LLM_PROVIDER={provider}"])
    env_path.write_text("\n".join(filtered) + "\n", encoding="utf-8")

    return JsonResponse({"status": "ok", "message": f"{provider.capitalize()} API key saved and activated!"})


def get_api_status(request: HttpRequest):
    """Returns active LLM provider status."""
    active_prov = (os.getenv("LLM_PROVIDER") or "").lower()
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_groq = bool(os.getenv("GROQ_API_KEY")) and active_prov == "groq"
    has_key = has_gemini or has_openai or has_groq
    provider_name = active_prov.capitalize() if has_key else "Offline"
    return JsonResponse({"has_key": has_key, "provider": provider_name})


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

    # 1. Prepare Workspace (Clone/Pull if remote GitHub repo)
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
        workspace_path=workspace_path,
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

    if hasattr(task, "patch") and task.patch.diff and task.patch.patch_hash != submitted_hash:
        return JsonResponse({"error": "Patch hash mismatch. Approval rejected."}, status=400)

    Approval.objects.create(task=task, patch_hash=submitted_hash or "", approver=data.get("approver", "human_reviewer"), decision=decision)

    if decision == "APPROVED":
        task.status = Task.Status.APPROVED
        ok, workspace_path, _ = prepare_workspace(task.project.repo_url)
        deploy_info = deploy_approved_patch(
            workspace_path=workspace_path,
            repo_url=task.project.repo_url,
            task_id=task.id,
            prompt=task.prompt,
            diff_text=task.patch.diff if hasattr(task, "patch") else "",
        )
        task.pr_url = deploy_info.get("html_url", "")
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
