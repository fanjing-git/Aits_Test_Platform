"""Permission matrix tests for task T006."""

from types import SimpleNamespace
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from apps.users.models import UserProfile
from apps.users.permissions import (
    HasPlatformPermission,
    IsAdminRole,
    IsDeveloperRole,
    IsTesterRole,
    IsTestLeaderRole,
    IsViewerRole,
    PermissionScope,
    PlatformAction,
    get_permission_scope,
)


class PlatformPermissionMatrixTests(TestCase):
    """Verify every role/action combination in the PRD permission matrix."""

    expected_actions = {
        UserProfile.Role.ADMIN: set(PlatformAction),
        UserProfile.Role.TEST_LEADER: set(PlatformAction)
        - {PlatformAction.MANAGE_USERS},
        UserProfile.Role.TESTER: {
            PlatformAction.CREATE_CASE,
            PlatformAction.EXECUTE_TEST,
            PlatformAction.VIEW_REPORT,
            PlatformAction.CONFIGURE_NOTIFICATIONS,
        },
        UserProfile.Role.DEVELOPER: {
            PlatformAction.EXECUTE_TEST,
            PlatformAction.VIEW_REPORT,
            PlatformAction.CONFIGURE_NOTIFICATIONS,
        },
        UserProfile.Role.VIEWER: {PlatformAction.VIEW_REPORT},
    }

    def test_all_role_action_decisions_match_the_prd(self) -> None:
        """Each role should allow exactly the operations assigned by the PRD."""
        for role, allowed_actions in self.expected_actions.items():
            for action in PlatformAction:
                with self.subTest(role=role, action=action):
                    scope = get_permission_scope(role, action)
                    self.assertEqual(scope is not None, action in allowed_actions)

    def test_limited_operations_expose_the_required_scope(self) -> None:
        """Developer and personal settings access must retain ownership limits."""
        self.assertEqual(
            get_permission_scope(
                UserProfile.Role.DEVELOPER,
                PlatformAction.EXECUTE_TEST,
            ),
            PermissionScope.OWN_MODULE,
        )
        self.assertEqual(
            get_permission_scope(
                UserProfile.Role.TESTER,
                PlatformAction.CONFIGURE_NOTIFICATIONS,
            ),
            PermissionScope.PERSONAL,
        )

    def test_unknown_role_or_action_is_denied(self) -> None:
        """Unexpected permission data must fail closed."""
        self.assertIsNone(get_permission_scope("unknown", PlatformAction.VIEW_REPORT))
        self.assertIsNone(get_permission_scope(UserProfile.Role.ADMIN, "unknown"))


class DrfPlatformPermissionTests(TestCase):
    """Verify reusable DRF permission behavior and safe defaults."""

    def setUp(self) -> None:
        """Create one authenticated user whose role can be changed per test."""
        self.user = get_user_model().objects.create_user(username="permission-user")
        self.permission = HasPlatformPermission()

    def request_for(self, user: Any) -> SimpleNamespace:
        """Build the minimal request contract consumed by permission classes."""
        return SimpleNamespace(user=user)

    def test_declared_allowed_action_passes(self) -> None:
        """An authenticated role should pass its declared global operation."""
        self.user.profile.role = UserProfile.Role.TESTER
        self.user.profile.save(update_fields=("role",))
        view = SimpleNamespace(permission_action=PlatformAction.CREATE_CASE)

        self.assertTrue(self.permission.has_permission(self.request_for(self.user), view))

    def test_anonymous_missing_profile_and_missing_action_are_denied(self) -> None:
        """Incomplete identity or view configuration must fail closed."""
        declared_view = SimpleNamespace(permission_action=PlatformAction.VIEW_REPORT)
        self.assertFalse(
            self.permission.has_permission(
                self.request_for(AnonymousUser()),
                declared_view,
            )
        )

        self.user.profile.delete()
        self.user._state.fields_cache.pop("profile", None)
        self.assertFalse(
            self.permission.has_permission(self.request_for(self.user), declared_view)
        )
        self.assertFalse(
            self.permission.has_permission(
                self.request_for(self.user),
                SimpleNamespace(),
            )
        )

    def test_scoped_object_access_requires_and_uses_view_checker(self) -> None:
        """Scoped access must be denied unless the owning view validates it."""
        self.user.profile.role = UserProfile.Role.DEVELOPER
        self.user.profile.save(update_fields=("role",))
        request = self.request_for(self.user)
        obj = object()
        view_without_checker = SimpleNamespace(
            permission_action=PlatformAction.EXECUTE_TEST
        )
        self.assertFalse(
            self.permission.has_object_permission(request, view_without_checker, obj)
        )

        checked_scopes: list[PermissionScope] = []

        def scope_checker(
            checked_request: Any,
            checked_object: Any,
            scope: PermissionScope,
        ) -> bool:
            checked_scopes.append(scope)
            return checked_request is request and checked_object is obj

        view_with_checker = SimpleNamespace(
            permission_action=PlatformAction.EXECUTE_TEST,
            has_permission_scope=scope_checker,
        )
        self.assertTrue(
            self.permission.has_object_permission(request, view_with_checker, obj)
        )
        self.assertEqual(checked_scopes, [PermissionScope.OWN_MODULE])


class ExactRolePermissionTests(TestCase):
    """Verify the five explicit role permission classes."""

    role_permissions = {
        UserProfile.Role.ADMIN: IsAdminRole,
        UserProfile.Role.TEST_LEADER: IsTestLeaderRole,
        UserProfile.Role.TESTER: IsTesterRole,
        UserProfile.Role.DEVELOPER: IsDeveloperRole,
        UserProfile.Role.VIEWER: IsViewerRole,
    }

    def test_each_role_class_accepts_only_its_matching_role(self) -> None:
        """Exact role classes must not accidentally inherit another role's access."""
        for actual_role in self.role_permissions:
            user = get_user_model().objects.create_user(username=f"user-{actual_role}")
            user.profile.role = actual_role
            user.profile.save(update_fields=("role",))
            request = SimpleNamespace(user=user)
            for expected_role, permission_class in self.role_permissions.items():
                with self.subTest(actual=actual_role, expected=expected_role):
                    self.assertEqual(
                        permission_class().has_permission(request, SimpleNamespace()),
                        actual_role == expected_role,
                    )
