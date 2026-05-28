# Generated manually for vector stores

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def assign_default_workspace(apps, schema_editor):
    Workspace = apps.get_model("core", "Workspace")
    VectorStore = apps.get_model("core", "VectorStore")
    default = Workspace.objects.filter(slug="default").first()
    if default:
        VectorStore.objects.filter(workspace__isnull=True).update(workspace=default)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_workspaces_and_secret_links"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VectorStore",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text="Unique name for this vector store within a workspace (used in scripts)",
                        max_length=100,
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True,
                        help_text="Optional description of what this vector store is used for",
                    ),
                ),
                (
                    "dimensions",
                    models.PositiveIntegerField(
                        default=1536,
                        help_text="Expected embedding vector length (e.g. 1536 for OpenAI text-embedding-3-small)",
                    ),
                ),
                (
                    "sqlite_filename",
                    models.CharField(
                        blank=True,
                        help_text="SQLite file name under data/vectorstores/",
                        max_length=255,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_vectorstores",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vectorstores",
                        to="core.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "vector store",
                "verbose_name_plural": "vector stores",
                "db_table": "vectorstores",
                "ordering": ["name"],
            },
        ),
        migrations.AddConstraint(
            model_name="vectorstore",
            constraint=models.UniqueConstraint(
                fields=("workspace", "name"),
                name="unique_vectorstore_name_per_workspace",
            ),
        ),
        migrations.RunPython(assign_default_workspace, migrations.RunPython.noop),
    ]
