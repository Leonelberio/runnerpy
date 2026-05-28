# Generated manually for workspaces and secret-script linking

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_default_workspace_and_migrate(apps, schema_editor):
    User = apps.get_model("core", "User")
    Workspace = apps.get_model("core", "Workspace")
    WorkspaceMembership = apps.get_model("core", "WorkspaceMembership")
    Script = apps.get_model("core", "Script")
    Secret = apps.get_model("core", "Secret")
    Environment = apps.get_model("core", "Environment")
    Tag = apps.get_model("core", "Tag")
    DataStore = apps.get_model("core", "DataStore")

    workspace, _ = Workspace.objects.get_or_create(
        slug="default",
        defaults={
            "id": uuid.uuid4(),
            "name": "Default",
            "description": "Default workspace for existing resources",
        },
    )

    for user in User.objects.all():
        WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": "admin"},
        )

    Script.objects.filter(workspace__isnull=True).update(workspace=workspace)
    Secret.objects.filter(workspace__isnull=True).update(workspace=workspace)
    Environment.objects.filter(workspace__isnull=True).update(workspace=workspace)
    Tag.objects.filter(workspace__isnull=True).update(workspace=workspace)
    DataStore.objects.filter(workspace__isnull=True).update(workspace=workspace)

    # Preserve prior behavior: all secrets linked to all scripts in the workspace
    scripts = list(Script.objects.filter(workspace=workspace))
    secrets = list(Secret.objects.filter(workspace=workspace))
    for script in scripts:
        if secrets:
            script.secrets.set(secrets)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_field_updates"),
    ]

    operations = [
        migrations.CreateModel(
            name="Workspace",
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
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_workspaces",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "workspace",
                "verbose_name_plural": "workspaces",
                "db_table": "workspaces",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceMembership",
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
                    "role",
                    models.CharField(
                        choices=[("admin", "Admin"), ("member", "Member")],
                        default="member",
                        max_length=20,
                    ),
                ),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="core.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "workspace membership",
                "verbose_name_plural": "workspace memberships",
                "db_table": "workspace_memberships",
                "ordering": ["workspace__name", "user__email"],
                "unique_together": {("workspace", "user")},
            },
        ),
        migrations.AddField(
            model_name="script",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="scripts",
                to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="secret",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="secrets",
                to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="environment",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="environments",
                to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tags",
                to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="datastore",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="datastores",
                to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="script",
            name="secrets",
            field=models.ManyToManyField(
                blank=True,
                help_text="Secrets to inject as environment variables when this script runs",
                related_name="scripts",
                to="core.secret",
            ),
        ),
        migrations.AlterField(
            model_name="secret",
            name="key",
            field=models.CharField(
                help_text="Environment variable name (uppercase, underscores allowed)",
                max_length=100,
            ),
        ),
        migrations.AlterField(
            model_name="tag",
            name="name",
            field=models.CharField(
                help_text="Tag name (must be unique within a workspace)",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="datastore",
            name="name",
            field=models.CharField(
                help_text="Unique name for this data store within a workspace (used in scripts)",
                max_length=100,
            ),
        ),
        migrations.RunPython(create_default_workspace_and_migrate, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="secret",
            constraint=models.UniqueConstraint(
                fields=("workspace", "key"),
                name="unique_secret_key_per_workspace",
            ),
        ),
        migrations.AddConstraint(
            model_name="tag",
            constraint=models.UniqueConstraint(
                fields=("workspace", "name"),
                name="unique_tag_name_per_workspace",
            ),
        ),
        migrations.AddConstraint(
            model_name="datastore",
            constraint=models.UniqueConstraint(
                fields=("workspace", "name"),
                name="unique_datastore_name_per_workspace",
            ),
        ),
    ]
