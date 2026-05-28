"""
Service for duplicating scripts within or across workspaces.
"""

from __future__ import annotations

from django.db import transaction

from core.models import Environment, Script, ScriptSchedule, Secret, Tag


class ScriptDuplicateError(Exception):
    """Raised when a script cannot be duplicated."""


class ScriptDuplicateService:
    """Duplicate scripts with optional secrets, tags, and schedule."""

    @staticmethod
    def generate_unique_name(base_name: str, workspace) -> str:
        """Return a unique script name within the target workspace."""
        candidate = f"{base_name} (Copy)"
        if not Script.objects.filter(workspace=workspace, name=candidate).exists():
            return candidate

        counter = 2
        while True:
            candidate = f"{base_name} (Copy {counter})"
            if not Script.objects.filter(workspace=workspace, name=candidate).exists():
                return candidate
            counter += 1

    @classmethod
    def resolve_environment(cls, source_script: Script, target_workspace) -> Environment:
        """Pick an environment in the target workspace for the duplicate."""
        if source_script.workspace_id == target_workspace.pk:
            return source_script.environment

        matched = Environment.objects.filter(
            workspace=target_workspace,
            name=source_script.environment.name,
            is_active=True,
        ).first()
        if matched:
            return matched

        default_env = Environment.objects.filter(
            workspace=target_workspace,
            is_default=True,
            is_active=True,
        ).first()
        if default_env:
            return default_env

        fallback = Environment.objects.filter(
            workspace=target_workspace,
            is_active=True,
        ).first()
        if fallback:
            return fallback

        raise ScriptDuplicateError(
            f'No active environment found in workspace "{target_workspace.name}". '
            "Create an environment there first."
        )

    @classmethod
    def _copy_tags(
        cls,
        source_script: Script,
        new_script: Script,
        target_workspace,
        *,
        copy_tags: bool,
        created_by,
    ) -> None:
        if not copy_tags:
            return

        tag_ids = []
        for tag in source_script.tags.all():
            if source_script.workspace_id == target_workspace.pk:
                tag_ids.append(tag.pk)
                continue

            existing = Tag.objects.filter(
                workspace=target_workspace,
                name__iexact=tag.name,
            ).first()
            if existing:
                tag_ids.append(existing.pk)
            else:
                new_tag = Tag.objects.create(
                    workspace=target_workspace,
                    name=tag.name,
                    color=tag.color,
                    created_by=created_by,
                )
                tag_ids.append(new_tag.pk)

        if tag_ids:
            new_script.tags.set(tag_ids)

    @classmethod
    def _copy_secrets(
        cls,
        source_script: Script,
        new_script: Script,
        target_workspace,
        *,
        copy_secrets: bool,
        created_by,
    ) -> list[str]:
        """Copy or link secrets. Returns keys that were skipped (target already had them)."""
        if not copy_secrets:
            return []

        skipped_existing = []
        secret_ids = []

        for secret in source_script.secrets.all():
            if source_script.workspace_id == target_workspace.pk:
                secret_ids.append(secret.pk)
                continue

            existing = Secret.objects.filter(
                workspace=target_workspace,
                key=secret.key,
            ).first()
            if existing:
                secret_ids.append(existing.pk)
                skipped_existing.append(secret.key)
                continue

            copied = Secret(
                workspace=target_workspace,
                key=secret.key,
                encrypted_value=secret.encrypted_value,
                description=secret.description,
                created_by=created_by,
            )
            copied.save()
            secret_ids.append(copied.pk)

        if secret_ids:
            new_script.secrets.set(secret_ids)

        return skipped_existing

    @classmethod
    def _copy_schedule(
        cls,
        source_script: Script,
        new_script: Script,
        *,
        copy_schedule: bool,
        created_by,
    ) -> None:
        if not copy_schedule:
            ScriptSchedule.objects.create(
                script=new_script,
                run_mode=ScriptSchedule.RunMode.MANUAL,
                created_by=created_by,
            )
            return

        try:
            source_schedule = source_script.schedule
        except ScriptSchedule.DoesNotExist:
            ScriptSchedule.objects.create(
                script=new_script,
                run_mode=ScriptSchedule.RunMode.MANUAL,
                created_by=created_by,
            )
            return

        ScriptSchedule.objects.create(
            script=new_script,
            run_mode=source_schedule.run_mode,
            interval_minutes=source_schedule.interval_minutes,
            daily_times=list(source_schedule.daily_times or []),
            weekly_days=list(source_schedule.weekly_days or []),
            weekly_times=list(source_schedule.weekly_times or []),
            monthly_days=list(source_schedule.monthly_days or []),
            monthly_times=list(source_schedule.monthly_times or []),
            timezone=source_schedule.timezone,
            is_active=source_schedule.is_active,
            created_by=created_by,
        )

    @classmethod
    @transaction.atomic
    def duplicate(
        cls,
        source_script: Script,
        target_workspace,
        created_by,
        *,
        name: str | None = None,
        copy_secrets: bool = True,
        copy_tags: bool = True,
        copy_schedule: bool = True,
    ) -> tuple[Script, list[str]]:
        """
        Duplicate a script into target_workspace.

        Returns (new_script, skipped_secret_keys) where skipped_secret_keys lists
        secret keys that already existed in the target workspace and were linked
        instead of copied.
        """
        if source_script.is_archived:
            raise ScriptDuplicateError("Archived scripts cannot be duplicated.")

        environment = cls.resolve_environment(source_script, target_workspace)
        duplicate_name = (name or "").strip() or cls.generate_unique_name(
            source_script.name, target_workspace
        )

        if Script.objects.filter(workspace=target_workspace, name=duplicate_name).exists():
            raise ScriptDuplicateError(
                f'A script named "{duplicate_name}" already exists in that workspace.'
            )

        new_script = Script.objects.create(
            name=duplicate_name,
            description=source_script.description,
            code=source_script.code,
            environment=environment,
            workspace=target_workspace,
            timeout_seconds=source_script.timeout_seconds,
            is_enabled=source_script.is_enabled,
            notify_on=source_script.notify_on,
            notify_email=source_script.notify_email,
            notify_webhook_url=source_script.notify_webhook_url,
            notify_webhook_enabled=False,
            retention_days_override=source_script.retention_days_override,
            retention_count_override=source_script.retention_count_override,
            created_by=created_by,
        )

        cls._copy_tags(
            source_script,
            new_script,
            target_workspace,
            copy_tags=copy_tags,
            created_by=created_by,
        )
        skipped_secrets = cls._copy_secrets(
            source_script,
            new_script,
            target_workspace,
            copy_secrets=copy_secrets,
            created_by=created_by,
        )
        cls._copy_schedule(
            source_script,
            new_script,
            copy_schedule=copy_schedule,
            created_by=created_by,
        )

        if copy_schedule:
            from core.services.schedule_service import ScheduleService

            try:
                schedule = new_script.schedule
                if schedule.is_scheduled:
                    ScheduleService.sync_schedule(schedule)
            except ScriptSchedule.DoesNotExist:
                pass

        return new_script, skipped_secrets
