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
    Create a default workspace and membership if the user has none.
    Used after login and during migration for existing installs.
    """
    from core.models import Workspace, WorkspaceMembership

    if WorkspaceMembership.objects.filter(user=user).exists():
        return Workspace.objects.filter(memberships__user=user).first()

    workspace = Workspace.objects.create(
        name="Default",
        slug="default",
        created_by=user,
    )
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceMembership.Role.ADMIN,
    )
    return workspace
