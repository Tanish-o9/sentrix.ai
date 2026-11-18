"""Django Database Models for AETHER.

Stores authoritative records, task lifecycle, patches, and approval audit logs.
"""

from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=120)
    repo_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Task(models.Model):
    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        PLANNING = "PLANNING", "Planning"
        CODING = "CODING", "Coding"
        REVIEWING = "REVIEWING", "Reviewing"
        AWAITING_APPROVAL = "AWAITING_APPROVAL", "Awaiting Approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    prompt = models.TextField()
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.CREATED)
    plan = models.JSONField(null=True, blank=True)
    pr_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)


class TaskStep(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="steps")
    agent_name = models.CharField(max_length=60)
    step_type = models.CharField(max_length=60)
    output_summary = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class CodePatch(models.Model):
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="patch")
    patch_hash = models.CharField(max_length=64, db_index=True)
    diff = models.TextField()
    explanation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Approval(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="approvals")
    patch_hash = models.CharField(max_length=64)
    approver = models.CharField(max_length=80, default="human_reviewer")
    decision = models.CharField(max_length=20, choices=[("APPROVED", "Approved"), ("REJECTED", "Rejected")])
    created_at = models.DateTimeField(auto_now_add=True)
