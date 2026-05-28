"""
Tag management views for the control panel.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.decorators import workspace_required
from core.forms import TagForm
from core.models import Tag


def _tags_for(request):
    return Tag.objects.filter(workspace=request.workspace)


@workspace_required
def tag_list_view(request: HttpRequest) -> HttpResponse:
    """List all tags with script counts."""
    tags = _tags_for(request).order_by("name")
    return render(
        request,
        "cpanel/tags/list.html",
        {"tags": tags},
    )


@workspace_required
def tag_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new tag."""
    if request.method == "POST":
        form = TagForm(request.POST, workspace=request.workspace)
        if form.is_valid():
            tag = form.save(commit=False)
            tag.created_by = request.user
            tag.workspace = request.workspace
            tag.save()
            messages.success(request, f'Tag "{tag.name}" created successfully.')
            return redirect("cpanel:tag_list")
    else:
        form = TagForm(workspace=request.workspace)

    return render(
        request,
        "cpanel/tags/create.html",
        {"form": form},
    )


@workspace_required
def tag_edit_view(request: HttpRequest, pk) -> HttpResponse:
    """Edit an existing tag."""
    tag = get_object_or_404(_tags_for(request), pk=pk)

    if request.method == "POST":
        form = TagForm(request.POST, instance=tag, workspace=request.workspace)
        if form.is_valid():
            form.save()
            messages.success(request, f'Tag "{tag.name}" updated successfully.')
            return redirect("cpanel:tag_list")
    else:
        form = TagForm(instance=tag, workspace=request.workspace)

    return render(
        request,
        "cpanel/tags/edit.html",
        {"form": form, "tag": tag},
    )


@workspace_required
@require_POST
def tag_delete_view(request: HttpRequest, pk) -> HttpResponse:
    """Delete a tag."""
    tag = get_object_or_404(_tags_for(request), pk=pk)
    name = tag.name
    tag.delete()
    messages.success(request, f'Tag "{name}" deleted successfully.')
    return redirect("cpanel:tag_list")
