"""
Script views for the control panel.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import HttpRequest, HttpResponse

from core.decorators import workspace_required
from core.models import Script, Run, ScriptSchedule, ScheduleHistory, Tag, Secret
from core.forms import ScriptForm, ScheduleForm, ScriptDuplicateForm
from core.tasks import queue_script_run
from core.services.schedule_service import ScheduleService
from core.services.script_duplicate_service import ScriptDuplicateService, ScriptDuplicateError
from core.workspace_utils import set_active_workspace


def _scripts_for(request):
    return Script.objects.filter(workspace=request.workspace)


@workspace_required
def script_list_view(request: HttpRequest) -> HttpResponse:
    """List all scripts with optional filtering."""
    scripts = (
        _scripts_for(request)
        .select_related("environment", "created_by")
        .prefetch_related("tags", "secrets")
        .order_by("-updated_at")
    )

    status_filter = request.GET.get("status")
    if status_filter == "enabled":
        scripts = scripts.filter(is_enabled=True, archived_at__isnull=True)
    elif status_filter == "disabled":
        scripts = scripts.filter(is_enabled=False, archived_at__isnull=True)
    elif status_filter == "archived":
        scripts = scripts.filter(archived_at__isnull=False)
    else:
        scripts = scripts.filter(archived_at__isnull=True)

    tag_filter = request.GET.get("tag")
    selected_tag = None
    if tag_filter:
        try:
            selected_tag = Tag.objects.get(pk=tag_filter, workspace=request.workspace)
            scripts = scripts.filter(tags=selected_tag)
        except (Tag.DoesNotExist, ValueError):
            pass

    all_tags = Tag.objects.filter(workspace=request.workspace).order_by("name")

    return render(request, "cpanel/scripts/list.html", {
        "scripts": scripts,
        "status_filter": status_filter,
        "all_tags": all_tags,
        "selected_tag": selected_tag,
    })


@workspace_required
def script_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new script."""
    if request.method == "POST":
        form = ScriptForm(request.POST, workspace=request.workspace)
        if form.is_valid():
            script = form.save(commit=False)
            script.created_by = request.user
            script.workspace = request.workspace
            script.save()
            form.save_m2m()
            messages.success(request, f'Script "{script.name}" created successfully.')
            return redirect("cpanel:script_detail", pk=script.pk)
    else:
        form = ScriptForm(workspace=request.workspace)

    available_tags = Tag.objects.filter(workspace=request.workspace).order_by("name")
    available_secrets = Secret.objects.filter(workspace=request.workspace).order_by("key")
    return render(request, "cpanel/scripts/create.html", {
        "form": form,
        "available_tags": available_tags,
        "available_secrets": available_secrets,
        "selected_tag_ids": [],
        "selected_secret_ids": [],
    })


@workspace_required
def script_detail_view(request: HttpRequest, pk) -> HttpResponse:
    """View script details and recent runs."""
    script = get_object_or_404(
        _scripts_for(request)
        .select_related("environment", "created_by")
        .prefetch_related("tags", "secrets"),
        pk=pk,
    )
    recent_runs = script.runs.select_related("triggered_by").order_by("-created_at")[:10]

    schedule, _ = ScriptSchedule.objects.get_or_create(
        script=script,
        defaults={"created_by": request.user},
    )

    return render(request, "cpanel/scripts/detail.html", {
        "script": script,
        "recent_runs": recent_runs,
        "schedule": schedule,
    })


@workspace_required
def script_edit_view(request: HttpRequest, pk) -> HttpResponse:
    """Edit an existing script and its schedule."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    schedule, created = ScriptSchedule.objects.get_or_create(
        script=script,
        defaults={"created_by": request.user},
    )

    if request.method == "POST":
        form = ScriptForm(request.POST, instance=script, workspace=request.workspace)
        schedule_form = ScheduleForm(request.POST, instance=schedule)

        if form.is_valid() and schedule_form.is_valid():
            previous_config = {
                "run_mode": schedule.run_mode,
                "interval_minutes": schedule.interval_minutes,
                "daily_times": schedule.daily_times,
                "timezone": schedule.timezone,
                "is_active": schedule.is_active,
            }

            script = form.save(commit=False)
            script.save()
            form.save_m2m()
            schedule = schedule_form.save()

            new_config = {
                "run_mode": schedule.run_mode,
                "interval_minutes": schedule.interval_minutes,
                "daily_times": schedule.daily_times,
                "timezone": schedule.timezone,
                "is_active": schedule.is_active,
            }

            if previous_config != new_config:
                change_type = (
                    ScheduleHistory.ChangeType.CREATED
                    if created
                    else ScheduleHistory.ChangeType.UPDATED
                )
                ScheduleHistory.objects.create(
                    schedule=schedule,
                    change_type=change_type,
                    previous_config=previous_config if not created else None,
                    new_config=new_config,
                    changed_by=request.user,
                )

            ScheduleService.sync_schedule(schedule)

            messages.success(request, f'Script "{script.name}" updated successfully.')
            return redirect("cpanel:script_detail", pk=script.pk)
    else:
        form = ScriptForm(instance=script, workspace=request.workspace)
        schedule_form = ScheduleForm(instance=schedule)

    available_tags = Tag.objects.filter(workspace=request.workspace).order_by("name")
    available_secrets = Secret.objects.filter(workspace=request.workspace).order_by("key")
    selected_tag_ids = list(script.tags.values_list("pk", flat=True))
    selected_secret_ids = list(script.secrets.values_list("pk", flat=True))
    return render(request, "cpanel/scripts/edit.html", {
        "form": form,
        "schedule_form": schedule_form,
        "script": script,
        "available_tags": available_tags,
        "available_secrets": available_secrets,
        "selected_tag_ids": selected_tag_ids,
        "selected_secret_ids": selected_secret_ids,
    })


@workspace_required
@require_POST
def script_run_view(request: HttpRequest, pk) -> HttpResponse:
    """Trigger a manual script run."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    if not script.can_run:
        if script.is_archived:
            messages.error(request, "Cannot run an archived script.")
        else:
            messages.error(request, "Cannot run a disabled script.")
        return redirect("cpanel:script_detail", pk=pk)

    run = Run.objects.create(
        script=script,
        status=Run.Status.PENDING,
        triggered_by=request.user,
        code_snapshot=script.code,
    )

    try:
        queue_script_run(run)
        messages.info(request, f'Script "{script.name}" has been queued for execution.')
    except Exception as e:
        run.status = Run.Status.FAILED
        run.stderr = f"Failed to queue task: {str(e)}"
        run.save()
        messages.error(request, f"Failed to queue script: {str(e)}")

    return redirect("cpanel:run_detail", pk=run.pk)


@workspace_required
@require_POST
def script_toggle_view(request: HttpRequest, pk) -> HttpResponse:
    """Toggle script enabled/disabled state."""
    script = get_object_or_404(_scripts_for(request), pk=pk)
    script.is_enabled = not script.is_enabled
    script.save(update_fields=["is_enabled", "updated_at"])

    status = "enabled" if script.is_enabled else "disabled"
    messages.success(request, f'Script "{script.name}" is now {status}.')
    return redirect("cpanel:script_detail", pk=pk)


@workspace_required
@require_POST
def schedule_toggle_view(request: HttpRequest, pk) -> HttpResponse:
    """Toggle schedule active/inactive state."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    try:
        schedule = script.schedule
    except ScriptSchedule.DoesNotExist:
        messages.error(request, "No schedule configured for this script.")
        return redirect("cpanel:script_detail", pk=pk)

    previous_active = schedule.is_active
    schedule.is_active = not schedule.is_active
    schedule.save(update_fields=["is_active", "updated_at"])

    ScheduleHistory.objects.create(
        schedule=schedule,
        change_type=(
            ScheduleHistory.ChangeType.ENABLED
            if schedule.is_active
            else ScheduleHistory.ChangeType.DISABLED
        ),
        previous_config={"is_active": previous_active},
        new_config={"is_active": schedule.is_active},
        changed_by=request.user,
    )

    ScheduleService.sync_schedule(schedule)

    status = "enabled" if schedule.is_active else "paused"
    messages.success(request, f'Schedule for "{script.name}" is now {status}.')
    return redirect("cpanel:script_detail", pk=pk)


@workspace_required
def schedule_history_view(request: HttpRequest, pk) -> HttpResponse:
    """View schedule change history."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    try:
        schedule = script.schedule
        history = schedule.history.select_related("changed_by").order_by("-created_at")
    except ScriptSchedule.DoesNotExist:
        history = []
        schedule = None

    return render(request, "cpanel/scripts/schedule_history.html", {
        "script": script,
        "schedule": schedule,
        "history": history,
    })


@workspace_required
@require_POST
def webhook_enable_view(request: HttpRequest, pk) -> HttpResponse:
    """Enable webhook for a script (creates token if not exists)."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    if not script.webhook_token:
        script.create_webhook_token()
        messages.success(request, f'Webhook enabled for "{script.name}".')
    else:
        messages.info(request, "Webhook is already enabled.")

    return redirect("cpanel:script_detail", pk=pk)


@workspace_required
@require_POST
def webhook_disable_view(request: HttpRequest, pk) -> HttpResponse:
    """Disable webhook for a script (removes token)."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    if script.webhook_token:
        script.clear_webhook_token()
        messages.success(request, f'Webhook disabled for "{script.name}".')
    else:
        messages.info(request, "Webhook is already disabled.")

    return redirect("cpanel:script_detail", pk=pk)


@workspace_required
@require_POST
def webhook_regenerate_view(request: HttpRequest, pk) -> HttpResponse:
    """Regenerate webhook token (invalidates old URL)."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    script.regenerate_webhook_token()
    messages.success(
        request,
        f'Webhook URL regenerated for "{script.name}". The old URL is now invalid.',
    )

    return redirect("cpanel:script_detail", pk=pk)


@workspace_required
def script_duplicate_view(request: HttpRequest, pk) -> HttpResponse:
    """Duplicate a script within the active workspace or into another workspace."""
    script = get_object_or_404(
        _scripts_for(request)
        .select_related("environment", "workspace")
        .prefetch_related("tags", "secrets"),
        pk=pk,
    )

    if script.is_archived:
        messages.error(request, "Archived scripts cannot be duplicated.")
        return redirect("cpanel:script_detail", pk=pk)

    if request.method == "POST":
        form = ScriptDuplicateForm(
            request.POST,
            user=request.user,
            source_script=script,
        )
        if form.is_valid():
            target_workspace = form.cleaned_data["target_workspace"]
            try:
                new_script, skipped_secrets = ScriptDuplicateService.duplicate(
                    script,
                    target_workspace,
                    request.user,
                    name=form.cleaned_data["name"] or None,
                    copy_secrets=form.cleaned_data["copy_secrets"],
                    copy_tags=form.cleaned_data["copy_tags"],
                    copy_schedule=form.cleaned_data["copy_schedule"],
                )
            except ScriptDuplicateError as exc:
                messages.error(request, str(exc))
            else:
                message = (
                    f'Script duplicated as "{new_script.name}" in {target_workspace.name}.'
                )
                if skipped_secrets:
                    message += (
                        " Linked existing secrets (not copied): "
                        + ", ".join(skipped_secrets)
                        + "."
                    )
                messages.success(request, message)

                if target_workspace.pk != request.workspace.pk:
                    set_active_workspace(request, target_workspace)

                return redirect("cpanel:script_detail", pk=new_script.pk)
    else:
        form = ScriptDuplicateForm(user=request.user, source_script=script)

    suggested_name = ScriptDuplicateService.generate_unique_name(
        script.name,
        script.workspace,
    )

    return render(request, "cpanel/scripts/duplicate.html", {
        "form": form,
        "script": script,
        "suggested_name": suggested_name,
    })


@workspace_required
@require_POST
def script_archive_view(request: HttpRequest, pk) -> HttpResponse:
    """Archive a script (soft delete)."""
    from django.utils import timezone

    script = get_object_or_404(_scripts_for(request), pk=pk)

    if script.is_archived:
        messages.info(request, f'Script "{script.name}" is already archived.')
        return redirect("cpanel:script_detail", pk=pk)

    script.archived_at = timezone.now()
    script.archived_by = request.user
    script.save(update_fields=["archived_at", "archived_by", "updated_at"])

    try:
        schedule = script.schedule
        if schedule.is_active:
            schedule.is_active = False
            schedule.save(update_fields=["is_active", "updated_at"])
            ScheduleService.sync_schedule(schedule)
    except ScriptSchedule.DoesNotExist:
        pass

    messages.success(request, f'Script "{script.name}" has been archived.')
    return redirect("cpanel:script_list")


@workspace_required
@require_POST
def script_restore_view(request: HttpRequest, pk) -> HttpResponse:
    """Restore an archived script."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    if not script.is_archived:
        messages.info(request, f'Script "{script.name}" is not archived.')
        return redirect("cpanel:script_detail", pk=pk)

    script.archived_at = None
    script.archived_by = None
    script.save(update_fields=["archived_at", "archived_by", "updated_at"])

    messages.success(request, f'Script "{script.name}" has been restored.')
    return redirect("cpanel:script_detail", pk=pk)


@workspace_required
@require_POST
def script_delete_view(request: HttpRequest, pk) -> HttpResponse:
    """Permanently delete an archived script."""
    script = get_object_or_404(_scripts_for(request), pk=pk)

    if not script.is_archived:
        messages.error(request, "Only archived scripts can be permanently deleted.")
        return redirect("cpanel:script_detail", pk=pk)

    name = script.name
    script.delete()

    messages.success(request, f'Script "{name}" has been permanently deleted.')
    return redirect("cpanel:script_list")
