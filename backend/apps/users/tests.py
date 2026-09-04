"""Tests for user profiles and their Django Admin integration."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.users.admin import UserProfileInline
from apps.users.models import UserProfile


class UserProfileModelTests(TestCase):
    """Verify profile lifecycle, roles, validation, and persistence."""

    def test_new_user_receives_default_viewer_profile(self) -> None:
        """A newly created user should have one default profile."""
        user = get_user_model().objects.create_user(username="new-user")

        self.assertEqual(user.profile.role, UserProfile.Role.VIEWER)
        self.assertEqual(user.profile.preferences, {})
        self.assertEqual(user.profile.notification_preferences, {})

    def test_profile_accepts_each_supported_role(self) -> None:
        """All five contracted role values should pass model validation."""
        user = get_user_model().objects.create_user(username="role-user")

        for role, _label in UserProfile.Role.choices:
            user.profile.role = role
            user.profile.full_clean()

    def test_preferences_reject_non_object_json(self) -> None:
        """Preference fields should reject ambiguous top-level JSON arrays."""
        user = get_user_model().objects.create_user(username="invalid-prefs")
        user.profile.preferences = ["unexpected-list"]

        with self.assertRaises(ValidationError):
            user.profile.full_clean()


class UserProfileAdminTests(TestCase):
    """Verify profiles are editable through Django Admin."""

    def test_profile_is_registered_and_inlined_on_user_admin(self) -> None:
        """Admin should expose both direct and user-inline profile editing."""
        user_admin = admin.site._registry[get_user_model()]

        self.assertIn(UserProfile, admin.site._registry)
        self.assertIn(UserProfileInline, user_admin.inlines)

    def test_admin_user_page_exposes_profile_fields(self) -> None:
        """A privileged user should see editable profile fields on the user page."""
        user_model = get_user_model()
        administrator = user_model.objects.create_superuser(
            username="administrator",
            email="admin@example.com",
            password="safe-test-password",
        )
        target_user = user_model.objects.create_user(username="managed-user")
        self.client.force_login(administrator)

        response = self.client.get(f"/admin/auth/user/{target_user.pk}/change/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile-0-role")
        self.assertContains(response, "profile-0-preferences")
        self.assertContains(response, "profile-0-notification_preferences")
