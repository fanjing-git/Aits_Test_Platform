"""T019 model validation, isolation, encryption and lifecycle tests."""
import os
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models.functions import Cast
from django.test import TestCase
from apps.environments.models import Environment
from apps.projects.models import Project
from core.utils.crypto import SecretDecryptionError


class EnvironmentTests(TestCase):
    """Exercise persistence rather than making external service requests."""

    def setUp(self) -> None:
        """Create an isolated project and disposable encryption key."""
        key_patch = patch.dict(os.environ, {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        key_patch.start()
        self.addCleanup(key_patch.stop)
        user = get_user_model().objects.create_user(username="environment-owner")
        self.project = Project.objects.create(name="Environment tests", created_by=user)
        self.other_project = Project.objects.create(name="Other environment tests", created_by=user)

    def make_environment(self, name: str = "test") -> Environment:
        """Create a local-only example without contacting its endpoint."""
        return Environment.objects.create(project=self.project, name=name, base_url="https://example.com/api/")

    def test_four_types_and_independent_default_objects(self) -> None:
        """Persist all deployment stages with conservative initial status."""
        for name in Environment.Name.values:
            env = self.make_environment(name)
            env.refresh_from_db()
            self.assertEqual(env.status, Environment.Status.UNAVAILABLE)
            self.assertEqual(env.health_status, Environment.HealthStatus.UNKNOWN)
            self.assertEqual(env.database_config, {})
        self.assertEqual(self.project.environments.count(), 4)
        first, second = Environment(), Environment()
        first.variables["example"] = True
        self.assertEqual(second.variables, {})

    def test_unique_type_is_scoped_to_project(self) -> None:
        """Enforce uniqueness even when bulk writes bypass model validation."""
        self.make_environment()
        Environment.objects.create(project=self.other_project, name="test", base_url="https://example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Environment.objects.bulk_create([Environment(project=self.project, name="test", base_url="https://example.com")])

    def test_invalid_choices_and_urls(self) -> None:
        """Reject invalid metadata and URLs embedding login credentials."""
        for field, value in (("name", "qa"), ("status", "bad"), ("health_status", "bad"), ("base_url", "ftp://example.com"), ("base_url", "https://user:pass@example.com"), ("health_check_url", "not-a-url")):
            with self.subTest(field=field, value=value):
                env = Environment(project=self.project, name="test", base_url="https://example.com")
                setattr(env, field, value)
                with self.assertRaises(ValidationError):
                    env.save()

    def test_json_shapes_including_empty_values(self) -> None:
        """Reject arrays, scalars and null instead of storing malformed config."""
        for field in ("database_config", "auth_config", "variables"):
            for value in ([], None, "", 0, False, ["value"]):
                with self.subTest(field=field, value=value):
                    env = Environment(project=self.project, name="test", base_url="https://example.com")
                    setattr(env, field, value)
                    with self.assertRaises(ValidationError):
                        env.save()

    def test_encrypted_roundtrip_and_queryset_update(self) -> None:
        """ORM updates cannot bypass encryption of nested secrets."""
        env = self.make_environment()
        for field in ("database_config", "auth_config", "variables"):
            payload = {"nested": {"password": "fake-secret-t019"}, "port": 5432}
            Environment.objects.filter(pk=env.pk).update(**{field: payload})
            raw = Environment.objects.filter(pk=env.pk).annotate(stored=Cast(field, output_field=models.TextField())).values_list("stored", flat=True).get()
            self.assertNotIn("fake-secret-t019", raw)
            self.assertIn("gAAAA", raw)
            env.refresh_from_db()
            self.assertEqual(getattr(env, field), payload)
        env.description = "metadata edit"
        env.save()
        env.refresh_from_db()
        self.assertEqual(env.auth_config["nested"]["password"], "fake-secret-t019")

    def test_wrong_key_fails_without_secret_disclosure(self) -> None:
        """Never silently replace unreadable credentials with empty values."""
        env = self.make_environment()
        with patch.dict(os.environ, {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()}):
            with self.assertRaises(SecretDecryptionError):
                env.refresh_from_db()

    def test_status_is_independent_of_health_and_project_delete_cascades(self) -> None:
        """A healthy probe must not undo maintenance state."""
        env = self.make_environment()
        env.status = Environment.Status.MAINTENANCE
        env.health_status = Environment.HealthStatus.HEALTHY
        env.save()
        env.refresh_from_db()
        self.assertEqual(env.status, Environment.Status.MAINTENANCE)
        self.project.delete()
        self.assertFalse(Environment.objects.filter(pk=env.pk).exists())
