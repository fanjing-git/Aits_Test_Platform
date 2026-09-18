"""Platform-role and project-role matrix tests for requirement assets."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.projects.models import Project, ProjectMember
from apps.requirement_analysis.permissions import can_manage_requirements
from apps.users.models import UserProfile


class RequirementPermissionMatrixTests(TestCase):
    """Ensure requirement and case-generation writes honor the PRD matrix."""

    def setUp(self) -> None:
        user_model = get_user_model()
        self.tester = user_model.objects.create_user(username="requirement-perm-tester")
        self.developer = user_model.objects.create_user(username="requirement-perm-developer")
        self.viewer = user_model.objects.create_user(username="requirement-perm-viewer")
        for user, role in (
            (self.tester, UserProfile.Role.TESTER),
            (self.developer, UserProfile.Role.DEVELOPER),
            (self.viewer, UserProfile.Role.VIEWER),
        ):
            user.profile.role = role
            user.profile.save(update_fields=("role",))
        self.project = Project.objects.create(
            name="Requirement permission project", created_by=self.tester
        )
        for user, role in (
            (self.tester, ProjectMember.Role.OWNER),
            (self.developer, ProjectMember.Role.MANAGER),
            (self.viewer, ProjectMember.Role.MANAGER),
        ):
            ProjectMember.objects.create(project=self.project, user=user, role=role)

    def test_case_capability_is_required_for_requirement_writes(self) -> None:
        """Project management alone must not grant case-generation writes."""
        self.assertTrue(can_manage_requirements(self.tester, self.project))
        self.assertFalse(can_manage_requirements(self.developer, self.project))
        self.assertFalse(can_manage_requirements(self.viewer, self.project))
