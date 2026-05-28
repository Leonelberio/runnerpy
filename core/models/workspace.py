"""
Workspace (organization) models for multi-tenant resource scoping.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Workspace(models.Model):
    """
    An isolated workspace containing scripts, secrets, and related resources.
    System settings (email, workers, S3) remain instance-wide.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_workspaces",
    )

    class Meta:
        db_table = "workspaces"
        verbose_name = "workspace"
        verbose_name_plural = "workspaces"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def generate_unique_slug(cls, name: str, exclude_pk=None) -> str:
        base = slugify(name) or "workspace"
        slug = base
        counter = 1
        qs = cls.objects.filter(slug=slug)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        while qs.exists():
            slug = f"{base}-{counter}"
            counter += 1
            qs = cls.objects.filter(slug=slug)
            if exclude_pk:
                qs = qs.exclude(pk=exclude_pk)
        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.generate_unique_slug(self.name, exclude_pk=self.pk)
        super().save(*args, **kwargs)


class WorkspaceMembership(models.Model):
    """Links users to workspaces with a role."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workspace_memberships"
        verbose_name = "workspace membership"
        verbose_name_plural = "workspace memberships"
        unique_together = [["workspace", "user"]]
        ordering = ["workspace__name", "user__email"]

    def __str__(self):
        return f"{self.user.email} @ {self.workspace.name} ({self.role})"
