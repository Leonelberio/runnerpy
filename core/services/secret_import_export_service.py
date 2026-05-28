"""
Export and import workspace secrets as JSON (password-gated in views).
"""

from __future__ import annotations

import json
import re
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Secret
from core.services import EncryptionService

EXPORT_FORMAT = "pyrunner-secrets"
EXPORT_VERSION = 1
MAX_IMPORT_FILE_BYTES = 1 * 1024 * 1024
SECRET_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SecretImportExportError(Exception):
    """Raised when import/export payload is invalid."""


class SecretImportExportService:
    """Build and apply workspace secret export files."""

    @classmethod
    def export_secrets(cls, workspace) -> dict[str, Any]:
        """Return a JSON-serializable export payload with decrypted secret values."""
        if not EncryptionService.is_configured():
            raise SecretImportExportError(
                "Encryption is not configured. Set ENCRYPTION_KEY first."
            )

        secrets = []
        for secret in Secret.objects.filter(workspace=workspace).order_by("key"):
            secrets.append(
                {
                    "key": secret.key,
                    "value": secret.get_decrypted_value(),
                    "description": secret.description,
                }
            )

        return {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "exported_at": timezone.now().isoformat(),
            "workspace": {
                "id": str(workspace.pk),
                "name": workspace.name,
                "slug": workspace.slug,
            },
            "secrets": secrets,
        }

    @classmethod
    def serialize_export(cls, payload: dict[str, Any]) -> str:
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def parse_import_file(cls, raw: bytes) -> dict[str, Any]:
        if len(raw) > MAX_IMPORT_FILE_BYTES:
            raise SecretImportExportError(
                f"Import file is too large (max {MAX_IMPORT_FILE_BYTES // (1024 * 1024)} MB)."
            )

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretImportExportError("Import file must be valid UTF-8 JSON.") from exc

        cls.validate_export_payload(data)
        return data

    @classmethod
    def validate_export_payload(cls, data: Any) -> None:
        if not isinstance(data, dict):
            raise SecretImportExportError("Invalid secrets export file.")

        if data.get("format") != EXPORT_FORMAT:
            raise SecretImportExportError(
                "Unrecognized file format. Use a PyRunner secrets export file."
            )

        version = data.get("version")
        if version != EXPORT_VERSION:
            raise SecretImportExportError(
                f"Unsupported export version: {version!r}. Expected {EXPORT_VERSION}."
            )

        secrets = data.get("secrets")
        if not isinstance(secrets, list):
            raise SecretImportExportError("Export file is missing a secrets list.")

    @classmethod
    @transaction.atomic
    def import_secrets(
        cls,
        workspace,
        data: dict[str, Any],
        created_by,
        *,
        overwrite_existing: bool = False,
    ) -> dict[str, int]:
        """Import secrets into a workspace. Returns counts of created/updated/skipped."""
        if not EncryptionService.is_configured():
            raise SecretImportExportError(
                "Encryption is not configured. Set ENCRYPTION_KEY first."
            )

        cls.validate_export_payload(data)

        created = 0
        updated = 0
        skipped = 0

        for index, item in enumerate(data.get("secrets", []), start=1):
            if not isinstance(item, dict):
                raise SecretImportExportError(f"Secret entry #{index} is invalid.")

            key = (item.get("key") or "").strip().upper()
            value = item.get("value")
            description = (item.get("description") or "").strip()

            if not key:
                raise SecretImportExportError(f"Secret entry #{index} is missing a key.")
            if not SECRET_KEY_PATTERN.match(key):
                raise SecretImportExportError(
                    f"Secret entry #{index} has an invalid key: {key!r}."
                )
            if value is None or value == "":
                raise SecretImportExportError(
                    f"Secret entry #{index} ({key}) is missing a value."
                )
            if not isinstance(value, str):
                raise SecretImportExportError(
                    f"Secret entry #{index} ({key}) must have a string value."
                )
            if len(value) > 10000:
                raise SecretImportExportError(
                    f"Secret entry #{index} ({key}) value is too long (max 10,000 characters)."
                )

            existing = Secret.objects.filter(workspace=workspace, key=key).first()
            if existing:
                if not overwrite_existing:
                    skipped += 1
                    continue
                existing.set_value(value)
                existing.description = description
                existing.save(update_fields=["encrypted_value", "description", "updated_at"])
                updated += 1
                continue

            secret = Secret(
                workspace=workspace,
                key=key,
                description=description,
                created_by=created_by,
            )
            secret.set_value(value)
            secret.save()
            created += 1

        return {"created": created, "updated": updated, "skipped": skipped}
