"""
VectorStore models for AI agent embedding storage.
"""

import uuid

from django.conf import settings
from django.db import models


class VectorStore(models.Model):
    """
    A named SQLite vector database for scripts and AI agents.
    Supports add, search, upsert, delete, and per-session conversation memory.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(
        max_length=100,
        help_text="Unique name for this vector store within a workspace (used in scripts)",
    )

    description = models.TextField(
        blank=True,
        help_text="Optional description of what this vector store is used for",
    )

    dimensions = models.PositiveIntegerField(
        default=1536,
        help_text="Expected embedding vector length (e.g. 1536 for OpenAI text-embedding-3-small)",
    )

    sqlite_filename = models.CharField(
        max_length=255,
        blank=True,
        help_text="SQLite file name under data/vectorstores/",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_vectorstores",
    )

    workspace = models.ForeignKey(
        "Workspace",
        on_delete=models.CASCADE,
        related_name="vectorstores",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "vectorstores"
        verbose_name = "vector store"
        verbose_name_plural = "vector stores"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                name="unique_vectorstore_name_per_workspace",
            ),
        ]

    def __str__(self):
        return self.name
