"""
View decorators for workspace-scoped control panel views.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from core.workspace_utils import (
    ensure_default_workspace,
    resolve_workspace,
    set_active_workspace,
)


def workspace_required(view_func):
    """Ensure the user has an active workspace before running the view."""

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        workspace = resolve_workspace(request)
        if workspace is None:
            workspace = ensure_default_workspace(request.user)
            if workspace:
                set_active_workspace(request, workspace)
        if workspace is None:
            return redirect("cpanel:workspace_create")
        request.workspace = workspace
        return view_func(request, *args, **kwargs)

    return wrapper


def workspace_admin_required(view_func):
    """Require admin role in the active workspace."""

    @workspace_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from core.models import WorkspaceMembership

        membership = WorkspaceMembership.objects.filter(
            workspace=request.workspace,
            user=request.user,
        ).first()
        if not membership or membership.role != WorkspaceMembership.Role.ADMIN:
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            return redirect("cpanel:dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper
