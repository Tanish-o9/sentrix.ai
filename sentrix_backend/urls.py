from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("ast/", views.ast_view, name="ast-view"),
    path("settings/api-key/", views.set_api_key, name="set-api-key"),
    path("settings/api-status/", views.get_api_status, name="api-status"),
    path("projects/", views.project_list_create, name="project-list-create"),
    path("tasks/", views.task_list_create, name="task-list-create"),
    path("tasks/<int:task_id>/", views.task_detail, name="task-detail"),
    path("tasks/<int:task_id>/run/", views.run_task, name="task-run"),
    path("tasks/<int:task_id>/approve/", views.approve_task, name="task-approve"),
    path("tasks/<int:task_id>/update-diff/", views.update_patch_diff, name="update-patch-diff"),
    path("tasks/<int:task_id>/download-patch/", views.download_patch, name="download-patch"),
    path("webhooks/github/", views.github_webhook, name="github-webhook"),
]
