"""
Workspace management views for the control panel.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.decorators import workspace_required
from core.forms import WorkspaceForm
from core.models import Workspace, WorkspaceMembership
from core.workspace_utils import (
    get_user_workspaces,
    set_active_workspace,
    user_can_access_workspace,
)


@login_required
def workspace_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new workspace."""
    if request.method == "POST":
        form = WorkspaceForm(request.POST)
        if form.is_valid():
            workspace = form.save(commit=False)
            workspace.created_by = request.user
            workspace.save()
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=request.user,
                role=WorkspaceMembership.Role.ADMIN,
            )
            set_active_workspace(request, workspace)
            messages.success(request, f'Workspace "{workspace.name}" created.')
            return redirect("cpanel:dashboard")
    else:
        form = WorkspaceForm()

    return render(
        request,
        "cpanel/workspaces/create.html",
        {"form": form},
    )


@login_required
@require_POST
def workspace_switch_view(request: HttpRequest) -> HttpResponse:
    """Switch the active workspace."""
    workspace_id = request.POST.get("workspace_id")
    workspace = get_object_or_404(Workspace, pk=workspace_id)

    if not user_can_access_workspace(request.user, workspace):
        messages.error(request, "You do not have access to that workspace.")
        return redirect("cpanel:dashboard")

    set_active_workspace(request, workspace)
    messages.success(request, f'Switched to workspace "{workspace.name}".')
    return redirect(request.POST.get("next") or "cpanel:dashboard")


@workspace_required
def workspace_settings_view(request: HttpRequest) -> HttpResponse:
    """View and edit workspace settings."""
    workspace = request.workspace
    membership = WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=request.user,
    ).first()
    is_admin = (
        request.user.is_superuser
        or (membership and membership.role == WorkspaceMembership.Role.ADMIN)
    )

    if request.method == "POST" and is_admin:
        form = WorkspaceForm(request.POST, instance=workspace)
        if form.is_valid():
            form.save()
            messages.success(request, "Workspace updated.")
            return redirect("cpanel:workspace_settings")
    else:
        form = WorkspaceForm(instance=workspace)

    members = (
        WorkspaceMembership.objects.filter(workspace=workspace)
        .select_related("user")
        .order_by("user__email")
    )

    return render(
        request,
        "cpanel/workspaces/settings.html",
        {
            "form": form,
            "workspace": workspace,
            "members": members,
            "is_admin": is_admin,
            "user_workspaces": get_user_workspaces(request.user),
        },
    )
