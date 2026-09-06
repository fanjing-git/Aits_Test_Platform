"""Verification and lifecycle services for third-party Skill packages.

The service accepts already-provided artifact bytes or a local file path. It
does not perform HTTP requests, import package code, or invoke entrypoints.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.projects.permissions import is_platform_admin
from apps.skills.models import SkillInstallation
from apps.skills.sources import SkillManifest, SkillSourceError


MAX_ARTIFACT_BYTES = 50 * 1024 * 1024


class SkillInstallationError(ValueError):
    """Raised when an installation lifecycle transition is not allowed."""


@dataclass(frozen=True, slots=True)
class ArtifactVerification:
    """Computed evidence retained for an installation audit entry."""

    file_hash: str
    commit_hash: str | None = None
    version: str | None = None


def sha256_bytes(content: bytes) -> str:
    """Return the lowercase SHA-256 digest for artifact bytes."""
    return hashlib.sha256(content).hexdigest()


def _artifact_bytes(artifact: bytes | bytearray | str | Path) -> bytes:
    if isinstance(artifact, (bytes, bytearray)):
        content = bytes(artifact)
    else:
        path = Path(artifact)
        try:
            if not path.is_file():
                raise SkillInstallationError("artifact file was not found")
            if path.stat().st_size > MAX_ARTIFACT_BYTES:
                raise SkillInstallationError("artifact exceeds the 50 MB limit")
            content = path.read_bytes()
        except OSError as exc:
            raise SkillInstallationError("artifact could not be read") from exc
    if not content:
        raise SkillInstallationError("artifact is empty")
    if len(content) > MAX_ARTIFACT_BYTES:
        raise SkillInstallationError("artifact exceeds the 50 MB limit")
    return content


def verify_artifact(
    manifest: SkillManifest,
    artifact: bytes | bytearray | str | Path,
    *,
    artifact_version: str | None = None,
    observed_commit_hash: str | None = None,
) -> ArtifactVerification:
    """Verify the locked version and declared file or commit hash."""
    try:
        if artifact_version is not None and artifact_version != manifest.version:
            raise SkillInstallationError("artifact version does not match the locked manifest version")
        if not manifest.file_hash and not manifest.commit_hash:
            raise SkillInstallationError("manifest must declare a file_hash or commit_hash before installation")
        content_hash = sha256_bytes(_artifact_bytes(artifact))
        if manifest.file_hash and content_hash != manifest.file_hash.casefold():
            raise SkillInstallationError("artifact file hash does not match the manifest")
        commit_hash = observed_commit_hash.casefold() if observed_commit_hash else None
        if manifest.commit_hash:
            if not commit_hash:
                raise SkillInstallationError("a commit hash is required for this source")
            if commit_hash != manifest.commit_hash.casefold():
                raise SkillInstallationError("artifact commit hash does not match the manifest")
        return ArtifactVerification(content_hash, commit_hash, artifact_version or manifest.version)
    except SkillSourceError as exc:
        raise SkillInstallationError(str(exc)) from exc


def _require_admin(user: Any) -> None:
    if not user or not is_platform_admin(user):
        raise SkillInstallationError("only a platform administrator may manage Skill installations")


@transaction.atomic
def request_installation(manifest: SkillManifest, requested_by: Any | None = None) -> SkillInstallation:
    """Create a pending, auditable installation request from a normalized manifest."""
    return SkillInstallation.objects.create(
        source_type=manifest.source.source_type.value,
        source_url=manifest.source.address,
        version=manifest.version,
        manifest=manifest.as_dict(),
        commit_hash=manifest.commit_hash or "",
        file_hash=manifest.file_hash or "",
        requested_by=requested_by,
        status=SkillInstallation.Status.PENDING,
    )


def verify_installation(
    installation: SkillInstallation,
    artifact: bytes | bytearray | str | Path,
    *,
    artifact_version: str | None = None,
    observed_commit_hash: str | None = None,
) -> SkillInstallation:
    """Verify an installation request and persist evidence or a safe failure."""
    manifest = SkillManifest.from_dict(installation.manifest)
    try:
        evidence = verify_artifact(
            manifest,
            artifact,
            artifact_version=artifact_version,
            observed_commit_hash=observed_commit_hash,
        )
    except SkillInstallationError as exc:
        installation.status = SkillInstallation.Status.FAILED
        installation.error_message = str(exc)
        installation.save(update_fields=("status", "error_message", "updated_at"))
        raise
    installation.file_hash = evidence.file_hash
    installation.commit_hash = evidence.commit_hash or installation.commit_hash
    installation.status = SkillInstallation.Status.VERIFIED
    installation.error_message = ""
    installation.save(update_fields=("file_hash", "commit_hash", "status", "error_message", "updated_at"))
    return installation


@transaction.atomic
def approve_installation(installation: SkillInstallation, reviewer: Any) -> SkillInstallation:
    """Approve only a verified request; unverified artifacts cannot be approved."""
    _require_admin(reviewer)
    if installation.status != SkillInstallation.Status.VERIFIED:
        raise SkillInstallationError("only a verified installation can be approved")
    installation.approved_by = reviewer
    installation.approved_at = timezone.now()
    installation.save(update_fields=("approved_by", "approved_at", "updated_at"))
    return installation


@transaction.atomic
def install_verified(installation: SkillInstallation, installer: Any) -> SkillInstallation:
    """Mark an approved package installed without importing or executing its code."""
    _require_admin(installer)
    if installation.status != SkillInstallation.Status.VERIFIED or installation.approved_by_id is None:
        raise SkillInstallationError("installation requires verification and administrator approval")
    installation.status = SkillInstallation.Status.INSTALLED
    installation.installed_by = installer
    installation.installed_at = timezone.now()
    installation.error_message = ""
    installation.save(update_fields=("status", "installed_by", "installed_at", "error_message", "updated_at"))
    return installation


@transaction.atomic
def rollback_installation(installation: SkillInstallation, actor: Any) -> SkillInstallation:
    """Disable the linked Skill and retain the installation record for audit."""
    _require_admin(actor)
    if installation.status not in {SkillInstallation.Status.INSTALLED, SkillInstallation.Status.VERIFIED}:
        raise SkillInstallationError("only an installed or verified package can be rolled back")
    if installation.skill_id:
        installation.skill.status = installation.skill.Status.DISABLED
        installation.skill.save(update_fields=("status", "updated_at"))
    installation.status = SkillInstallation.Status.ROLLED_BACK
    installation.rolled_back_at = timezone.now()
    installation.save(update_fields=("status", "rolled_back_at", "updated_at"))
    return installation


@transaction.atomic
def uninstall_installation(installation: SkillInstallation, actor: Any) -> SkillInstallation:
    """Disable an installed Skill while retaining its source and hash evidence."""
    _require_admin(actor)
    if installation.status != SkillInstallation.Status.INSTALLED:
        raise SkillInstallationError("only an installed package can be uninstalled")
    if installation.skill_id:
        installation.skill.status = installation.skill.Status.DISABLED
        installation.skill.save(update_fields=("status", "updated_at"))
    installation.status = SkillInstallation.Status.UNINSTALLED
    installation.save(update_fields=("status", "updated_at"))
    return installation


__all__ = [
    "ArtifactVerification",
    "MAX_ARTIFACT_BYTES",
    "SkillInstallationError",
    "approve_installation",
    "install_verified",
    "request_installation",
    "rollback_installation",
    "sha256_bytes",
    "uninstall_installation",
    "verify_artifact",
    "verify_installation",
]
