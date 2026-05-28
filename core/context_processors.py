"""
Context processors for PyRunner templates.
"""

from pyrunner.version import __version__

from core.workspace_utils import get_user_workspaces


def pyrunner_version(request):
    """Add PyRunner version to template context."""
    return {
        "pyrunner_version": __version__,
    }


def workspace_context(request):
    """Add active workspace and user's workspaces to template context."""
    workspace = getattr(request, "workspace", None)
    workspaces = []
    if request.user.is_authenticated:
        workspaces = list(get_user_workspaces(request.user))
    return {
        "active_workspace": workspace,
        "user_workspaces": workspaces,
    }
