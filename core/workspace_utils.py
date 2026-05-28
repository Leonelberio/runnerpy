"""
Helpers for resolving and scoping the active workspace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import HttpRequest

if TYPE_CHECKING:
    from core.models import Workspace


SESSION_WORKSPACE_KEY = "active_workspace_id"


def get_user_workspaces(user):
    """Return workspaces the user belongs to."""
    from core.models import Workspace

    if not user.is_authenticated:
        return Workspace.objects.none()
    return (
        Workspace.objects.filter(memberships__user=user)
        .distinct()
        .order_by("name")
    )


def resolve_workspace(request: HttpRequest) -> Workspace | None:
    """Resolve the active workspace from session or default to first membership."""
    from core.models import Workspace

    if not request.user.is_authenticated:
        return None

    workspaces = get_user_workspaces(request.user)
    if not workspaces.exists():
        return None

    workspace_id = request.session.get(SESSION_WORKSPACE_KEY)
    if workspace_id:
        workspace = workspaces.filter(pk=workspace_id).first()
        if workspace:
            return workspace

    workspace = workspaces.first()
    if workspace:
        request.session[SESSION_WORKSPACE_KEY] = str(workspace.pk)
    return workspace


def set_active_workspace(request: HttpRequest, workspace) -> None:
    """Persist the user's active workspace in the session."""
    request.session[SESSION_WORKSPACE_KEY] = str(workspace.pk)


def user_can_access_workspace(user, workspace) -> bool:
    if not user.is_authenticated:
        return False
    return workspace.memberships.filter(user=user).exists()


def ensure_default_workspace(user):
    """
    Ensure the user belongs to a workspace, joining the default if needed.

    Migration 0022 may create the Default workspace before any users exist
    (e.g. fresh Railway deploy + setup wizard). Reuse slug "default" instead
    of creating a duplicate.
    """
    from core.models import Workspace, WorkspaceMembership

    existing = (
        Workspace.objects.filter(memberships__user=user)
        .order_by("name")
        .first()
    )
    if existing:
        return existing

    workspace, _ = Workspace.objects.get_or_create(
        slug="default",
        defaults={
            "name": "Default",
            "description": "Default workspace",
            "created_by": user,
        },
    )
    WorkspaceMembership.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={"role": WorkspaceMembership.Role.ADMIN},
    )
    return workspace
