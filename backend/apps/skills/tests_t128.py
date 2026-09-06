"""Focused tests for the T128 third-party Skill source protocol."""
from unittest import TestCase

from apps.skills.sources import (
    PERMISSION_KEYS,
    SkillSourceError,
    SkillSourceType,
    discover_skill_manifest,
    parse_source_reference,
)


def _manifest(**overrides):
    value = {
        "name": "remote-demo",
        "version": "1.2.3",
        "author": "AITS Team",
        "license": "MIT",
        "permissions": {key: False for key in PERMISSION_KEYS},
    }
    value.update(overrides)
    return value


class SkillSourceProtocolTests(TestCase):
    def test_all_supported_sources_normalize_without_network_access(self):
        cases = (
            ("local", "local://skills/demo", SkillSourceType.LOCAL),
            ("github", "https://github.com/acme/demo?ref=v1.2.3", SkillSourceType.GITHUB),
            ("skillhub", "https://skillhub.example/skills/demo?version=1.2.3", SkillSourceType.SKILLHUB),
            ("package", "https://downloads.example/demo-1.2.3.tar.gz", SkillSourceType.PACKAGE),
        )
        for source, address, expected in cases:
            reference = parse_source_reference(source, address)
            self.assertEqual(reference.source_type, expected)
            normalized = discover_skill_manifest(address, _manifest(), source=source)
            self.assertEqual(normalized.source.source_type, expected)
            self.assertEqual(normalized.version, "1.2.3")

    def test_source_type_can_be_inferred_from_address(self):
        self.assertEqual(
            parse_source_reference(None, "https://github.com/acme/demo").source_type,
            SkillSourceType.GITHUB,
        )
        self.assertEqual(
            parse_source_reference(None, "https://downloads.example/demo-1.0.0.zip").source_type,
            SkillSourceType.PACKAGE,
        )
        self.assertEqual(parse_source_reference(None, "skills/demo").source_type, SkillSourceType.LOCAL)

    def test_manifest_accepts_structured_source_block(self):
        manifest = _manifest(source={"type": "github", "url": "https://github.com/acme/demo", "version": "1.2.3"})
        normalized = discover_skill_manifest("https://github.com/acme/demo", manifest)
        self.assertEqual(normalized.source.source_type, SkillSourceType.GITHUB)

    def test_manifest_requires_complete_permission_declaration(self):
        incomplete = _manifest(permissions={"network": False})
        with self.assertRaisesRegex(SkillSourceError, "missing"):
            discover_skill_manifest("local://skills/demo", incomplete, source="local")
        normalized = discover_skill_manifest("local://skills/demo", _manifest(permissions=["network"]), source="local")
        self.assertTrue(normalized.permissions["network"])
        self.assertFalse(normalized.permissions["file"])

    def test_invalid_or_unsafe_references_fail_closed(self):
        with self.assertRaises(SkillSourceError):
            parse_source_reference("github", "https://evil.example/acme/demo")
        with self.assertRaises(SkillSourceError):
            parse_source_reference("local", "local://../outside")
        with self.assertRaises(SkillSourceError):
            parse_source_reference("package", "https://downloads.example/demo/latest")
        with self.assertRaises(SkillSourceError):
            discover_skill_manifest("local://skills/demo", _manifest(permissions={"network": "yes"}), source="local")

    def test_normalized_manifest_is_stable_and_never_executes_source(self):
        manifest = discover_skill_manifest(
            "https://github.com/acme/demo?ref=v1.2.3",
            _manifest(description="  read only  ", entrypoint="package:Skill"),
            source="github",
        )
        self.assertEqual(manifest.as_dict()["source"], "github")
        self.assertEqual(manifest.description, "read only")
        self.assertEqual(manifest.entrypoint, "package:Skill")
        self.assertNotIn("execute", manifest.as_dict())
