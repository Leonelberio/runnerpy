"""
Dashboard view for the control panel.
"""
from django.http import JsonResponse
from django.shortcuts import render

from core.decorators import workspace_required
from core.models import Environment, Run, Script
from core.services.dashboard_service import DashboardService
from core.services.system_info_service import SystemInfoService


@workspace_required
def dashboard_view(request):
    """Main dashboard view with overview statistics for the active workspace."""
    ws = request.workspace
    script_qs = Script.objects.filter(workspace=ws)
    run_qs = Run.objects.filter(script__workspace=ws)

    stats = DashboardService.get_statistics(
        script_qs=script_qs,
        run_qs=run_qs,
    )

    runs_count = run_qs.count()
    environments_count = Environment.objects.filter(
        workspace=ws, is_active=True
    ).count()
    success_count = run_qs.filter(status=Run.Status.SUCCESS).count()
    failed_count = run_qs.filter(
        status__in=[Run.Status.FAILED, Run.Status.TIMEOUT]
    ).count()

    recent_runs = (
        run_qs.select_related("script", "triggered_by")
        .order_by("-created_at")[:5]
    )
    recent_scripts = (
        script_qs.select_related("environment")
        .order_by("-updated_at")[:5]
    )

    recent_failures = DashboardService.get_recent_failures(
        limit=5, run_qs=run_qs
    )
    upcoming_runs = DashboardService.get_upcoming_scheduled_runs(workspace=ws)
    system_health = DashboardService.get_system_health()
    system_resources = SystemInfoService.get_system_resources()

    context = {
        "scripts_count": stats["total_scripts"],
        "active_scripts_count": stats["active_scripts"],
        "runs_count": runs_count,
        "runs_today": stats["runs_today"],
        "runs_this_week": stats["runs_this_week"],
        "success_rate": stats["success_rate"],
        "queue_size": stats["queue_size"],
        "environments_count": environments_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "recent_runs": recent_runs,
        "recent_scripts": recent_scripts,
        "recent_failures": recent_failures,
        "upcoming_runs": upcoming_runs,
        "system_health": system_health,
        "system_resources": system_resources,
    }
    return render(request, "cpanel/dashboard.html", context)


@workspace_required
def system_resources_api(request):
    """AJAX endpoint for system resource metrics."""
    resources = SystemInfoService.get_system_resources()
    return JsonResponse(resources)
