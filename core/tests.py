from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    Environment,
    Script,
    ScriptSchedule,
    Secret,
    Tag,
    VectorStore,
    Workspace,
    WorkspaceMembership,
)
from core.services.script_duplicate_service import ScriptDuplicateError, ScriptDuplicateService
from core.services import EncryptionService
from core.services.secret_import_export_service import SecretImportExportService
from core.services.vectorstore_service import VectorstoreService

User = get_user_model()


class ScriptDuplicateServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tester",
            email="tester@example.com",
            password="testpass123",
        )
        self.workspace_a = Workspace.objects.create(name="Workspace A", slug="workspace-a")
        self.workspace_b = Workspace.objects.create(name="Workspace B", slug="workspace-b")
        for workspace in (self.workspace_a, self.workspace_b):
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=self.user,
                role=WorkspaceMembership.Role.ADMIN,
            )

        self.env_a = Environment.objects.create(
            name="Default",
            path="env-a-default",
            workspace=self.workspace_a,
            is_default=True,
            is_active=True,
            created_by=self.user,
        )
        self.env_b = Environment.objects.create(
            name="Default",
            path="env-b-default",
            workspace=self.workspace_b,
            is_default=True,
            is_active=True,
            created_by=self.user,
        )

        self.secret = Secret.objects.create(
            workspace=self.workspace_a,
            key="API_KEY",
            encrypted_value="encrypted-value",
            description="Test secret",
            created_by=self.user,
        )
        self.tag = Tag.objects.create(
            workspace=self.workspace_a,
            name="ops",
            color="blue",
            created_by=self.user,
        )
        self.source = Script.objects.create(
            name="Source Script",
            description="Original",
            code='print("hello")',
            environment=self.env_a,
            workspace=self.workspace_a,
            created_by=self.user,
        )
        self.source.tags.add(self.tag)
        self.source.secrets.add(self.secret)
        ScriptSchedule.objects.create(
            script=self.source,
            run_mode=ScriptSchedule.RunMode.INTERVAL,
            interval_minutes=30,
            is_active=True,
            created_by=self.user,
        )

    def test_duplicate_within_same_workspace(self):
        duplicate, skipped = ScriptDuplicateService.duplicate(
            self.source,
            self.workspace_a,
            self.user,
        )

        self.assertEqual(duplicate.name, "Source Script (Copy)")
        self.assertEqual(duplicate.workspace_id, self.workspace_a.pk)
        self.assertEqual(duplicate.code, self.source.code)
        self.assertEqual(list(duplicate.secrets.all()), [self.secret])
        self.assertEqual(list(duplicate.tags.all()), [self.tag])
        self.assertEqual(duplicate.schedule.run_mode, ScriptSchedule.RunMode.INTERVAL)
        self.assertFalse(duplicate.notify_webhook_enabled)
        self.assertEqual(skipped, [])

    def test_duplicate_to_other_workspace_copies_secrets_and_tags(self):
        duplicate, skipped = ScriptDuplicateService.duplicate(
            self.source,
            self.workspace_b,
            self.user,
        )

        self.assertEqual(duplicate.workspace_id, self.workspace_b.pk)
        self.assertEqual(duplicate.environment_id, self.env_b.pk)
        self.assertEqual(duplicate.secrets.count(), 1)
        copied_secret = duplicate.secrets.get()
        self.assertNotEqual(copied_secret.pk, self.secret.pk)
        self.assertEqual(copied_secret.key, "API_KEY")
        self.assertEqual(copied_secret.encrypted_value, self.secret.encrypted_value)
        self.assertEqual(duplicate.tags.count(), 1)
        self.assertEqual(duplicate.tags.get().name, "ops")
        self.assertEqual(skipped, [])

    def test_duplicate_links_existing_secret_in_target_workspace(self):
        existing = Secret.objects.create(
            workspace=self.workspace_b,
            key="API_KEY",
            encrypted_value="existing-value",
            created_by=self.user,
        )

        duplicate, skipped = ScriptDuplicateService.duplicate(
            self.source,
            self.workspace_b,
            self.user,
        )

        self.assertEqual(duplicate.secrets.get().pk, existing.pk)
        self.assertEqual(skipped, ["API_KEY"])

    def test_duplicate_archived_script_raises(self):
        self.source.archived_at = self.source.updated_at
        self.source.save(update_fields=["archived_at"])

        with self.assertRaises(ScriptDuplicateError):
            ScriptDuplicateService.duplicate(
                self.source,
                self.workspace_a,
                self.user,
            )

    def test_generate_unique_name_increments(self):
        Script.objects.create(
            name="Source Script (Copy)",
            code="pass",
            environment=self.env_a,
            workspace=self.workspace_a,
            created_by=self.user,
        )

        name = ScriptDuplicateService.generate_unique_name(
            "Source Script",
            self.workspace_a,
        )
        self.assertEqual(name, "Source Script (Copy 2)")


class VectorstoreServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="vector-user",
            email="vector-user@example.com",
            password="testpass123",
        )
        self.workspace = Workspace.objects.create(name="Vector WS", slug="vector-ws")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMembership.Role.ADMIN,
        )
        self.vectorstore = VectorStore.objects.create(
            name="agent_kb",
            description="Test KB",
            dimensions=3,
            workspace=self.workspace,
            created_by=self.user,
        )
        VectorstoreService.initialize_store(self.vectorstore)

    def tearDown(self):
        VectorstoreService.delete_store_file(self.vectorstore)

    def test_add_search_and_delete(self):
        VectorstoreService.add_chunk(
            self.vectorstore,
            "doc-1",
            "alpha content",
            [1.0, 0.0, 0.0],
            metadata={"tag": "a"},
        )
        VectorstoreService.add_chunk(
            self.vectorstore,
            "doc-2",
            "beta content",
            [0.0, 1.0, 0.0],
            metadata={"tag": "b"},
        )

        results = VectorstoreService.search(
            self.vectorstore,
            [1.0, 0.0, 0.0],
            top_k=1,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["doc_id"], "doc-1")
        self.assertGreater(results[0]["score"], 0.99)

        deleted = VectorstoreService.delete_document(self.vectorstore, "doc-1")
        self.assertEqual(deleted, 1)
        stats = VectorstoreService.get_stats(self.vectorstore)
        self.assertEqual(stats["chunk_count"], 1)


class SecretImportExportServiceTests(TestCase):
    def setUp(self):
        EncryptionService.reset()
        self.user = User.objects.create_user(
            username="secret-user",
            email="secret-user@example.com",
            password="testpass123",
        )
        self.workspace = Workspace.objects.create(name="Secrets WS", slug="secrets-ws")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMembership.Role.ADMIN,
        )

        secret = Secret(
            workspace=self.workspace,
            key="API_KEY",
            description="Primary key",
            created_by=self.user,
        )
        secret.set_value("super-secret-value")
        secret.save()

    def tearDown(self):
        EncryptionService.reset()

    def test_export_and_import_roundtrip(self):
        payload = SecretImportExportService.export_secrets(self.workspace)
        self.assertEqual(payload["format"], "pyrunner-secrets")
        self.assertEqual(len(payload["secrets"]), 1)
        self.assertEqual(payload["secrets"][0]["key"], "API_KEY")
        self.assertEqual(payload["secrets"][0]["value"], "super-secret-value")

        Secret.objects.filter(workspace=self.workspace).delete()
        result = SecretImportExportService.import_secrets(
            self.workspace,
            payload,
            self.user,
        )
        self.assertEqual(result, {"created": 1, "updated": 0, "skipped": 0})

        imported = Secret.objects.get(workspace=self.workspace, key="API_KEY")
        self.assertEqual(imported.get_decrypted_value(), "super-secret-value")
        self.assertEqual(imported.description, "Primary key")

    def test_import_skips_existing_by_default(self):
        payload = SecretImportExportService.export_secrets(self.workspace)
        payload["secrets"][0]["value"] = "changed-value"

        result = SecretImportExportService.import_secrets(
            self.workspace,
            payload,
            self.user,
        )
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(
            Secret.objects.get(workspace=self.workspace, key="API_KEY").get_decrypted_value(),
            "super-secret-value",
        )

    def test_import_overwrites_existing_when_requested(self):
        payload = SecretImportExportService.export_secrets(self.workspace)
        payload["secrets"][0]["value"] = "changed-value"

        result = SecretImportExportService.import_secrets(
            self.workspace,
            payload,
            self.user,
            overwrite_existing=True,
        )
        self.assertEqual(result["updated"], 1)
        self.assertEqual(
            Secret.objects.get(workspace=self.workspace, key="API_KEY").get_decrypted_value(),
            "changed-value",
        )


class EnsureDefaultWorkspaceTests(TestCase):
    def test_joins_existing_default_workspace_from_migration(self):
        """Fresh deploy: migration creates Default workspace before any users."""
        from core.workspace_utils import ensure_default_workspace

        workspace = Workspace.objects.create(
            name="Default",
            slug="default",
            description="Default workspace for existing resources",
        )
        user = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="testpass123",
        )

        result = ensure_default_workspace(user)

        self.assertEqual(result.pk, workspace.pk)
        self.assertEqual(Workspace.objects.filter(slug="default").count(), 1)
        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=workspace,
                user=user,
                role=WorkspaceMembership.Role.ADMIN,
            ).exists()
        )

    def test_creates_default_workspace_when_none_exists(self):
        from core.workspace_utils import ensure_default_workspace

        user = User.objects.create_user(
            username="solo",
            email="solo@example.com",
            password="testpass123",
        )

        result = ensure_default_workspace(user)

        self.assertEqual(result.slug, "default")
        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=result,
                user=user,
            ).exists()
        )

