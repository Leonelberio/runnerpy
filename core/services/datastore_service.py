"""
Service for datastore statistics and operations.
"""

from django.db.models import Sum
from django.db.models.functions import Coalesce, Length

from core.models import DataStore, DataStoreEntry
from core.services.environment_service import EnvironmentService


class DatastoreService:
    """Service for datastore statistics and operations."""

    @classmethod
    def get_datastores_with_stats(cls, workspace=None):
        """
        Get datastores annotated with size, optionally scoped to a workspace.
        """
        qs = DataStore.objects.all()
        if workspace is not None:
            qs = qs.filter(workspace=workspace)
        return qs.annotate(
            size_bytes=Coalesce(Sum(Length("entries__value_json")), 0),
        ).order_by("name")

    @classmethod
    def get_total_size(cls, workspace=None) -> int:
        """Get total size of datastore entries in bytes."""
        qs = DataStoreEntry.objects.all()
        if workspace is not None:
            qs = qs.filter(datastore__workspace=workspace)
        result = qs.aggregate(
            total=Coalesce(Sum(Length("value_json")), 0)
        )
        return result["total"]

    @classmethod
    def format_size(cls, size_bytes: int) -> str:
        """Format size in human-readable format."""
        return EnvironmentService.format_disk_usage(size_bytes)
