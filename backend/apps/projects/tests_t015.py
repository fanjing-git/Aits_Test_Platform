"""Project model tests for task T015."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.projects.models import Project, ProjectMember


class ProjectModelTests(TestCase):
    def setUp(self) -> None:
        self.owner = get_user_model().objects.create_user(username="project-owner")
        self.member = get_user_model().objects.create_user(username="project-member")
        self.project = Project.objects.create(
            name="Checkout Quality",
            description="Checkout service testing workspace",
            created_by=self.owner,
        )

    def test_project_defaults_and_json_settings(self) -> None:
        self.assertEqual(self.project.status, Project.Status.ACTIVE)
        self.assertEqual(self.project.settings, {})
        self.assertEqual(str(self.project), "Checkout Quality")

        self.project.settings = {"default_environment": "test"}
        self.project.full_clean()
        self.project.save()
        self.project.refresh_from_db()
        self.assertEqual(self.project.settings["default_environment"], "test")

    def test_project_can_add_members_with_distinct_roles(self) -> None:
        owner_membership = ProjectMember.objects.create(
            project=self.project, user=self.owner, role=ProjectMember.Role.OWNER
        )
        member_membership = ProjectMember.objects.create(
            project=self.project, user=self.member, role=ProjectMember.Role.MEMBER
        )

        self.assertEqual(self.project.memberships.count(), 2)
        self.assertEqual(owner_membership.role, ProjectMember.Role.OWNER)
        self.assertEqual(member_membership.role, ProjectMember.Role.MEMBER)

    def test_same_user_cannot_be_added_to_a_project_twice(self) -> None:
        ProjectMember.objects.create(project=self.project, user=self.member)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProjectMember.objects.create(project=self.project, user=self.member)

    def test_invalid_status_role_and_settings_are_rejected(self) -> None:
        self.project.status = "unknown"
        self.project.settings = []
        membership = ProjectMember(
            project=self.project,
            user=self.member,
            role="unknown",
        )

        with self.assertRaises(ValidationError):
            self.project.full_clean()
        with self.assertRaises(ValidationError):
            membership.full_clean()
