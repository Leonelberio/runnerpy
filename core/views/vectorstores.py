"""
Vector Store management views for the control panel.
"""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.decorators import workspace_required
from core.forms import VectorDocumentForm, VectorSearchForm, VectorStoreForm
from core.models import VectorStore
from core.services.vectorstore_service import VectorstoreError, VectorstoreService


def _vectorstores_for(request):
    return VectorStore.objects.filter(workspace=request.workspace)


@workspace_required
def vectorstore_list_view(request: HttpRequest) -> HttpResponse:
    """List all vector stores in the workspace."""
    vectorstores = VectorstoreService.get_vectorstores_with_stats(workspace=request.workspace)

    for store in vectorstores:
        store.size_display = VectorstoreService.format_size(store.size_bytes)

    total_size = sum(store.size_bytes for store in vectorstores)
    total_size_display = VectorstoreService.format_size(total_size)

    return render(
        request,
        "cpanel/vectorstores/list.html",
        {
            "vectorstores": vectorstores,
            "total_size_display": total_size_display,
            "vectorstore_count": len(vectorstores),
        },
    )


@workspace_required
def vectorstore_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new vector store."""
    if request.method == "POST":
        form = VectorStoreForm(request.POST, workspace=request.workspace)
        if form.is_valid():
            vectorstore = form.save(commit=False)
            vectorstore.created_by = request.user
            vectorstore.workspace = request.workspace
            vectorstore.save()
            VectorstoreService.initialize_store(vectorstore)

            messages.success(
                request,
                f'Vector store "{vectorstore.name}" created successfully.',
            )
            return redirect("cpanel:vectorstore_detail", pk=vectorstore.pk)
    else:
        form = VectorStoreForm(workspace=request.workspace)

    return render(request, "cpanel/vectorstores/create.html", {"form": form})


@workspace_required
def vectorstore_detail_view(request: HttpRequest, pk) -> HttpResponse:
    """View vector store details, documents, and search playground."""
    vectorstore = get_object_or_404(_vectorstores_for(request), pk=pk)
    documents = VectorstoreService.list_documents(vectorstore)
    stats = VectorstoreService.get_stats(vectorstore)

    document_form = VectorDocumentForm(vectorstore=vectorstore)
    search_form = VectorSearchForm(vectorstore=vectorstore)
    search_results = []

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_document":
            document_form = VectorDocumentForm(request.POST, vectorstore=vectorstore)
            if document_form.is_valid():
                try:
                    VectorstoreService.add_chunk(
                        vectorstore,
                        document_form.cleaned_data["doc_id"].strip(),
                        document_form.cleaned_data["content"],
                        document_form.cleaned_data["embedding"],
                        metadata=document_form.cleaned_data["metadata"],
                    )
                    messages.success(request, "Document chunk added.")
                    return redirect("cpanel:vectorstore_detail", pk=vectorstore.pk)
                except VectorstoreError as exc:
                    messages.error(request, str(exc))
        elif action == "search":
            search_form = VectorSearchForm(request.POST, vectorstore=vectorstore)
            if search_form.is_valid():
                try:
                    search_results = VectorstoreService.search(
                        vectorstore,
                        search_form.cleaned_data["embedding"],
                        top_k=search_form.cleaned_data["top_k"],
                    )
                except VectorstoreError as exc:
                    messages.error(request, str(exc))

    return render(
        request,
        "cpanel/vectorstores/detail.html",
        {
            "vectorstore": vectorstore,
            "documents": documents,
            "stats": stats,
            "document_form": document_form,
            "search_form": search_form,
            "search_results": search_results,
            "size_display": VectorstoreService.format_size(stats["size_bytes"]),
        },
    )


@workspace_required
def vectorstore_edit_view(request: HttpRequest, pk) -> HttpResponse:
    """Edit vector store metadata (dimensions locked after creation)."""
    vectorstore = get_object_or_404(_vectorstores_for(request), pk=pk)

    if request.method == "POST":
        form = VectorStoreForm(
            request.POST,
            instance=vectorstore,
            workspace=request.workspace,
        )
        if form.is_valid():
            updated = form.save(commit=False)
            updated.dimensions = vectorstore.dimensions
            updated.save(update_fields=["name", "description", "updated_at"])
            messages.success(
                request,
                f'Vector store "{vectorstore.name}" updated successfully.',
            )
            return redirect("cpanel:vectorstore_detail", pk=vectorstore.pk)
    else:
        form = VectorStoreForm(instance=vectorstore, workspace=request.workspace)
        form.fields["dimensions"].disabled = True

    return render(
        request,
        "cpanel/vectorstores/edit.html",
        {"form": form, "vectorstore": vectorstore},
    )


@workspace_required
@require_POST
def vectorstore_delete_view(request: HttpRequest, pk) -> HttpResponse:
    """Delete a vector store and its SQLite database."""
    vectorstore = get_object_or_404(_vectorstores_for(request), pk=pk)
    name = vectorstore.name
    VectorstoreService.delete_store_file(vectorstore)
    vectorstore.delete()

    messages.success(request, f'Vector store "{name}" deleted successfully.')
    return redirect("cpanel:vectorstore_list")


@workspace_required
@require_POST
def vectorstore_clear_view(request: HttpRequest, pk) -> HttpResponse:
    """Clear all vectors from a store."""
    vectorstore = get_object_or_404(_vectorstores_for(request), pk=pk)
    count = VectorstoreService.clear(vectorstore)
    messages.success(request, f'Cleared {count} vector chunks from "{vectorstore.name}".')
    return redirect("cpanel:vectorstore_detail", pk=vectorstore.pk)


@workspace_required
@require_POST
def vectorstore_document_delete_view(request: HttpRequest, pk, doc_id: str) -> HttpResponse:
    """Delete all chunks for a document."""
    vectorstore = get_object_or_404(_vectorstores_for(request), pk=pk)
    count = VectorstoreService.delete_document(vectorstore, doc_id)
    messages.success(request, f'Deleted document "{doc_id}" ({count} chunks).')
    return redirect("cpanel:vectorstore_detail", pk=vectorstore.pk)
