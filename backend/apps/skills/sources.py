"""Third-party Skill source references and manifest contracts.

This module deliberately stops at discovery and metadata validation.  It never
downloads, imports, or executes third-party code; installation is handled by
the later T129 task after approval and integrity checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from typing import Any, Mapping, Protocol, Self
from urllib.parse import parse_qs, urlparse, urlunparse


class SkillSourceError(ValueError):
    """Raised when a Skill source reference or manifest is unsafe or invalid."""


class SkillSourceType(StrEnum):
    """Supported third-party Skill source kinds."""

    LOCAL = "local"
    GITHUB = "github"
    SKILLHUB = "skillhub"
    PACKAGE = "package"


PERMISSION_KEYS: tuple[str, ...] = (
    "network",
    "file",
    "database",
    "external_command",
    "model",
    "knowledge",
    "environment_credentials",
)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillSourceError(f"manifest field '{field}' must be a non-empty string")
    return value.strip()


def _normalize_permissions(value: Any) -> dict[str, bool]:
    if isinstance(value, (list, tuple, set)):
        declared = {_required_string(item, "permissions") for item in value}
        unknown = declared - set(PERMISSION_KEYS)
        if unknown:
            raise SkillSourceError(f"manifest permissions contain unsupported keys: {sorted(unknown)}")
        return {key: key in declared for key in PERMISSION_KEYS}
    if not isinstance(value, Mapping):
        raise SkillSourceError("manifest field 'permissions' must be an object")
    unknown = set(value) - set(PERMISSION_KEYS)
    missing = set(PERMISSION_KEYS) - set(value)
    if unknown:
        raise SkillSourceError(f"manifest permissions contain unsupported keys: {sorted(unknown)}")
    if missing:
        raise SkillSourceError(f"manifest permissions are missing: {sorted(missing)}")
    if any(not isinstance(value[key], bool) for key in PERMISSION_KEYS):
        raise SkillSourceError("manifest permissions must contain boolean values")
    return {key: bool(value[key]) for key in PERMISSION_KEYS}


@dataclass(frozen=True, slots=True)
class SkillSourceReference:
    """A validated source location, without fetching its contents."""

    source_type: SkillSourceType
    address: str
    version: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        """Return a JSON-serializable representation for API and audit use."""
        return {"source_type": self.source_type.value, "address": self.address, "version": self.version}


@dataclass(frozen=True, slots=True)
class SkillManifest:
    """Normalized metadata required before a third-party Skill can be installed."""

    name: str
    version: str
    author: str
    license: str
    source: SkillSourceReference
    permissions: dict[str, bool]
    description: str = ""
    entrypoint: str = ""
    commit_hash: str | None = None
    file_hash: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], source: SkillSourceReference | None = None) -> Self:
        """Validate and normalize a manifest mapping supplied by a source."""
        if not isinstance(value, Mapping):
            raise SkillSourceError("Skill manifest must be an object")
        source_value = source or parse_source_reference(value.get("source"), value.get("source_url"), value.get("version"))
        version = _required_string(value.get("version"), "version")
        if any(char.isspace() for char in version):
            raise SkillSourceError("manifest field 'version' must not contain whitespace")
        return cls(
            name=_required_string(value.get("name"), "name"),
            version=version,
            author=_required_string(value.get("author"), "author"),
            license=_required_string(value.get("license"), "license"),
            source=source_value,
            permissions=_normalize_permissions(value.get("permissions")),
            description=str(value.get("description", "") or "").strip(),
            entrypoint=str(value.get("entrypoint", "") or "").strip(),
            commit_hash=_optional_hash(value.get("commit_hash"), "commit_hash"),
            file_hash=_optional_hash(value.get("file_hash"), "file_hash"),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the stable manifest shape used by adapters and future APIs."""
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "license": self.license,
            "description": self.description,
            "entrypoint": self.entrypoint,
            "source": self.source.source_type.value,
            "source_url": self.source.address,
            "source_version": self.source.version,
            "permissions": dict(self.permissions),
            "commit_hash": self.commit_hash,
            "file_hash": self.file_hash,
        }


def _optional_hash(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    result = _required_string(value, field).lower()
    if len(result) < 8 or any(char not in "0123456789abcdef" for char in result):
        raise SkillSourceError(f"manifest field '{field}' must be a hexadecimal hash")
    return result


def _parse_url(address: Any, field: str = "source_url") -> tuple[Any, str]:
    value = _required_string(address, field)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SkillSourceError(f"{field} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise SkillSourceError(f"{field} must not contain credentials")
    return parsed, value


def _canonical_http_url(parsed: Any) -> str:
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", parsed.query, ""))


def _github_reference(address: str) -> SkillSourceReference:
    parsed, _ = _parse_url(address)
    if parsed.hostname != "github.com":
        raise SkillSourceError("GitHub source must use github.com")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or any(part in {".", ".."} for part in parts[:2]):
        raise SkillSourceError("GitHub source must identify an owner and repository")
    query = parse_qs(parsed.query)
    version = (query.get("ref") or [None])[0]
    return SkillSourceReference(SkillSourceType.GITHUB, _canonical_http_url(parsed), version)


def _skillhub_reference(address: str) -> SkillSourceReference:
    parsed, _ = _parse_url(address)
    host = (parsed.hostname or "").lower()
    if "skillhub" not in host:
        raise SkillSourceError("SkillHub source must use a SkillHub host")
    query = parse_qs(parsed.query)
    version = (query.get("version") or [None])[0]
    return SkillSourceReference(SkillSourceType.SKILLHUB, _canonical_http_url(parsed), version)


def _package_reference(address: str) -> SkillSourceReference:
    parsed, original = _parse_url(address)
    suffix = parsed.path.lower()
    if not suffix.endswith((".whl", ".zip", ".tar.gz", ".tgz")):
        raise SkillSourceError("package source must point to a versioned .whl, .zip, .tar.gz or .tgz file")
    query = parse_qs(parsed.query)
    version = (query.get("version") or [None])[0]
    return SkillSourceReference(SkillSourceType.PACKAGE, _canonical_http_url(parsed), version)


def _local_reference(address: str) -> SkillSourceReference:
    value = _required_string(address, "source_url")
    if value.startswith("local://"):
        value = value[8:]
    if "\x00" in value or not value:
        raise SkillSourceError("local source path is invalid")
    path = PurePath(value)
    if any(part == ".." for part in path.parts):
        raise SkillSourceError("local source path must not traverse parent directories")
    return SkillSourceReference(SkillSourceType.LOCAL, str(path))


def parse_source_reference(source: Any, address: Any = None, version: Any = None) -> SkillSourceReference:
    """Resolve a source kind and validate its address without network access."""
    if isinstance(source, Mapping):
        source_value = source.get("type", source.get("source_type", ""))
        address = address if address is not None else source.get("url", source.get("address"))
        version = version if version is not None else source.get("version")
    else:
        source_value = source
    source_value = _required_string(source_value, "source") if source_value is not None and source_value != "" else ""
    address_value = address
    if address_value is None and source_value and "://" in source_value:
        address_value, source_value = source_value, ""
    normalized = source_value.casefold()
    if normalized in {"local", "file"}:
        reference = _local_reference(address_value)
    elif normalized == SkillSourceType.GITHUB:
        reference = _github_reference(address_value)
    elif normalized == SkillSourceType.SKILLHUB:
        reference = _skillhub_reference(address_value)
    elif normalized in {"package", "download", "archive"}:
        reference = _package_reference(address_value)
    elif not normalized:
        parsed = urlparse(_required_string(address_value, "source_url"))
        host = (parsed.hostname or "").lower()
        if host == "github.com":
            reference = _github_reference(address_value)
        elif "skillhub" in host:
            reference = _skillhub_reference(address_value)
        elif parsed.scheme in {"http", "https"}:
            reference = _package_reference(address_value)
        else:
            reference = _local_reference(address_value)
    else:
        raise SkillSourceError(f"unsupported Skill source type: {source_value}")
    if version is not None:
        version_value = _required_string(version, "version")
        reference = SkillSourceReference(reference.source_type, reference.address, version_value)
    return reference


class SkillSourceAdapter(Protocol):
    """Protocol implemented by source-specific discovery adapters."""

    source_type: SkillSourceType

    def discover(self, address: str, manifest: Mapping[str, Any]) -> SkillManifest:
        """Validate a source reference and normalize its manifest."""


class _BaseAdapter:
    source_type: SkillSourceType

    def discover(self, address: str, manifest: Mapping[str, Any]) -> SkillManifest:
        """Validate metadata only; no source contents are fetched."""
        source = parse_source_reference(self.source_type.value, address, manifest.get("version"))
        return SkillManifest.from_dict(manifest, source=source)


class LocalSkillAdapter(_BaseAdapter):
    """Discover a local package directory or archive path."""

    source_type = SkillSourceType.LOCAL


class GitHubSkillAdapter(_BaseAdapter):
    """Discover a GitHub repository reference."""

    source_type = SkillSourceType.GITHUB


class SkillHubAdapter(_BaseAdapter):
    """Discover a SkillHub registry reference."""

    source_type = SkillSourceType.SKILLHUB


class VersionedPackageAdapter(_BaseAdapter):
    """Discover a versioned downloadable package reference."""

    source_type = SkillSourceType.PACKAGE


_ADAPTERS: dict[SkillSourceType, SkillSourceAdapter] = {
    SkillSourceType.LOCAL: LocalSkillAdapter(),
    SkillSourceType.GITHUB: GitHubSkillAdapter(),
    SkillSourceType.SKILLHUB: SkillHubAdapter(),
    SkillSourceType.PACKAGE: VersionedPackageAdapter(),
}


def get_source_adapter(source: SkillSourceType | str, address: str | None = None) -> SkillSourceAdapter:
    """Return a registered adapter, optionally inferring the source from an address."""
    if address is not None:
        reference = parse_source_reference(source if source else None, address)
        source_type = reference.source_type
    else:
        source_type = SkillSourceType(str(source).casefold())
    try:
        return _ADAPTERS[source_type]
    except KeyError as exc:
        raise SkillSourceError(f"unsupported Skill source type: {source}") from exc


def discover_skill_manifest(address: str, manifest: Mapping[str, Any], source: str | None = None) -> SkillManifest:
    """Normalize a manifest through the correct adapter without downloading code."""
    reference = parse_source_reference(source, address, manifest.get("version")) if source else parse_source_reference(None, address, manifest.get("version"))
    return _ADAPTERS[reference.source_type].discover(reference.address, manifest)


__all__ = [
    "PERMISSION_KEYS",
    "GitHubSkillAdapter",
    "LocalSkillAdapter",
    "SkillHubAdapter",
    "SkillManifest",
    "SkillSourceAdapter",
    "SkillSourceError",
    "SkillSourceReference",
    "SkillSourceType",
    "VersionedPackageAdapter",
    "discover_skill_manifest",
    "get_source_adapter",
    "parse_source_reference",
]
