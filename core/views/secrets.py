"""
Secret management views for the control panel.
"""

from datetime import datetime

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.decorators import workspace_required
from core.forms import SecretCreateForm, SecretEditForm, SecretExportForm, SecretImportForm
from core.models import Secret
from core.services import EncryptionService
from core.services.secret_import_export_service import (
    SecretImportExportError,
    SecretImportExportService,
)


def _secrets_for(request):
    return Secret.objects.filter(workspace=request.workspace).prefetch_related("scripts")


@workspace_required
def secret_list_view(request: HttpRequest) -> HttpResponse:
    """List all secrets with masked values."""
    secrets = _secrets_for(request).order_by("key")
    encryption_configured = EncryptionService.is_configured()
    has_password = request.user.has_usable_password()

    return render(
        request,
        "cpanel/secrets/list.html",
        {
            "secrets": secrets,
            "encryption_configured": encryption_configured,
            "has_password": has_password,
        },
    )


@workspace_required
def secret_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new secret."""
    if not EncryptionService.is_configured():
        messages.error(
            request,
            "Encryption is not configured. Set ENCRYPTION_KEY in your environment.",
        )
        return redirect("cpanel:secret_list")

    if request.method == "POST":
        form = SecretCreateForm(request.POST, workspace=request.workspace)
        if form.is_valid():
            key = form.cleaned_data["key"]
            value = form.cleaned_data["value"]
            description = form.cleaned_data.get("description", "")
            linked_scripts = form.cleaned_data.get("scripts", [])

            secret = Secret(
                key=key,
                description=description,
                created_by=request.user,
                workspace=request.workspace,
            )
            secret.set_value(value)
            secret.save()

            for script in linked_scripts:
                script.secrets.add(secret)

            messages.success(request, f'Secret "{key}" created successfully.')
            return redirect("cpanel:secret_list")
    else:
        form = SecretCreateForm(workspace=request.workspace)

    return render(
        request,
        "cpanel/secrets/create.html",
        {"form": form},
    )


@workspace_required
def secret_edit_view(request: HttpRequest, pk) -> HttpResponse:
    """Edit an existing secret."""
    secret = get_object_or_404(_secrets_for(request), pk=pk)

    if request.method == "POST":
        form = SecretEditForm(
            request.POST,
            workspace=request.workspace,
            secret=secret,
        )
        if form.is_valid():
            new_value = form.cleaned_data.get("value")
            if new_value:
                secret.set_value(new_value)

            secret.description = form.cleaned_data.get("description", "")
            secret.save()

            linked_scripts = form.cleaned_data.get("scripts", [])
            secret.scripts.set(linked_scripts)

            messages.success(request, f'Secret "{secret.key}" updated successfully.')
            return redirect("cpanel:secret_list")
    else:
        form = SecretEditForm(
            workspace=request.workspace,
            secret=secret,
            initial={
                "description": secret.description,
                "scripts": secret.scripts.all(),
            },
        )

    return render(
        request,
        "cpanel/secrets/edit.html",
        {"form": form, "secret": secret},
    )


@workspace_required
def secret_export_view(request: HttpRequest) -> HttpResponse:
    """Export all workspace secrets after password confirmation."""
    if not EncryptionService.is_configured():
        messages.error(
            request,
            "Encryption is not configured. Set ENCRYPTION_KEY in your environment.",
        )
        return redirect("cpanel:secret_list")

    if not request.user.has_usable_password():
        messages.error(
            request,
            "Set an account password before exporting secrets.",
        )
        return redirect("cpanel:secret_list")

    if request.method == "POST":
        form = SecretExportForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                payload = SecretImportExportService.export_secrets(request.workspace)
            except SecretImportExportError as exc:
                messages.error(request, str(exc))
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"pyrunner-secrets-{request.workspace.slug}-{timestamp}.json"
                content = SecretImportExportService.serialize_export(payload)
                response = HttpResponse(content, content_type="application/json")
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
                return response
    else:
        form = SecretExportForm(user=request.user)

    secret_count = _secrets_for(request).count()

    return render(
        request,
        "cpanel/secrets/export.html",
        {
            "form": form,
            "secret_count": secret_count,
        },
    )


@workspace_required
def secret_import_view(request: HttpRequest) -> HttpResponse:
    """Import secrets from an export file after password confirmation."""
    if not EncryptionService.is_configured():
        messages.error(
            request,
            "Encryption is not configured. Set ENCRYPTION_KEY in your environment.",
        )
        return redirect("cpanel:secret_list")

    if not request.user.has_usable_password():
        messages.error(
            request,
            "Set an account password before importing secrets.",
        )
        return redirect("cpanel:secret_list")

    if request.method == "POST":
        form = SecretImportForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            try:
                result = SecretImportExportService.import_secrets(
                    request.workspace,
                    form.cleaned_data["secret_file"],
                    request.user,
                    overwrite_existing=form.cleaned_data["overwrite_existing"],
                )
            except SecretImportExportError as exc:
                messages.error(request, str(exc))
            else:
                parts = []
                if result["created"]:
                    parts.append(f'{result["created"]} created')
                if result["updated"]:
                    parts.append(f'{result["updated"]} updated')
                if result["skipped"]:
                    parts.append(f'{result["skipped"]} skipped')
                summary = ", ".join(parts) if parts else "no changes"
                messages.success(request, f"Secrets import complete: {summary}.")
                return redirect("cpanel:secret_list")
    else:
        form = SecretImportForm(user=request.user)

    return render(
        request,
        "cpanel/secrets/import.html",
        {"form": form},
    )


@workspace_required
@require_POST
def secret_delete_view(request: HttpRequest, pk) -> HttpResponse:
    """Delete a secret."""
    secret = get_object_or_404(_secrets_for(request), pk=pk)
    key = secret.key
    secret.delete()

    messages.success(request, f'Secret "{key}" deleted successfully.')
    return redirect("cpanel:secret_list")
