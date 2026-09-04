"""Project REST API tests for task T016."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.projects.models import Project, ProjectMember
from apps.users.models import UserProfile

User = get_user_model()


class ProjectApiTests(APITestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create_user(username="owner")
        self.manager = User.objects.create_user(username="manager")
        self.member = User.objects.create_user(username="member")
        self.outsider = User.objects.create_user(username="outsider")
        self.admin = User.objects.create_user(username="platform-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.list_url = reverse("projects:project-list")

    def create_project(self) -> tuple[Project, dict]:
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.list_url,
            {"name": "Payments", "description": "Payment quality workspace"},
            format="json",
        )
        return Project.objects.get(pk=response.data["id"]), response.data

    def test_creator_automatically_becomes_owner(self) -> None:
        project, data = self.create_project()

        membership = ProjectMember.objects.get(project=project, user=self.owner)
        self.assertEqual(membership.role, ProjectMember.Role.OWNER)
        self.assertEqual(data["current_role"], ProjectMember.Role.OWNER)
        self.assertEqual(data["member_count"], 1)

    def test_members_only_see_projects_they_belong_to_while_admin_sees_all(self) -> None:
        project, _ = self.create_project()
        Project.objects.create(name="Hidden", created_by=self.outsider)

        self.client.force_authenticate(self.owner)
        self.assertEqual(len(self.client.get(self.list_url).data), 1)

        self.client.force_authenticate(self.admin)
        response = self.client.get(self.list_url)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(
            next(item for item in response.data if item["id"] == str(project.pk))["current_role"],
            "platform_admin",
        )

    def test_owner_can_add_update_and_remove_member(self) -> None:
        project, _ = self.create_project()
        members_url = reverse("projects:project-members", args=(project.pk,))

        added = self.client.post(
            members_url,
            {"user_id": self.member.pk, "role": ProjectMember.Role.MEMBER},
            format="json",
        )
        self.assertEqual(added.status_code, status.HTTP_201_CREATED)
        detail_url = reverse(
            "projects:project-member-detail",
            args=(project.pk, added.data["id"]),
        )
        changed = self.client.patch(
            detail_url, {"role": ProjectMember.Role.VIEWER}, format="json"
        )
        self.assertEqual(changed.status_code, status.HTTP_200_OK)
        self.assertEqual(changed.data["role"], ProjectMember.Role.VIEWER)
        self.assertEqual(self.client.delete(detail_url).status_code, status.HTTP_204_NO_CONTENT)

    def test_manager_can_edit_project_and_members_but_not_delete_project(self) -> None:
        project, _ = self.create_project()
        ProjectMember.objects.create(
            project=project, user=self.manager, role=ProjectMember.Role.MANAGER
        )
        detail_url = reverse("projects:project-detail", args=(project.pk,))
        members_url = reverse("projects:project-members", args=(project.pk,))
        self.client.force_authenticate(self.manager)

        self.assertEqual(
            self.client.patch(detail_url, {"description": "Updated"}, format="json").status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(
                members_url,
                {"user_id": self.member.pk, "role": ProjectMember.Role.MEMBER},
                format="json",
            ).status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(self.client.delete(detail_url).status_code, status.HTTP_403_FORBIDDEN)

    def test_member_is_read_only_and_outsider_cannot_discover_project(self) -> None:
        project, _ = self.create_project()
        ProjectMember.objects.create(project=project, user=self.member)
        detail_url = reverse("projects:project-detail", args=(project.pk,))

        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.patch(detail_url, {"name": "Denied"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_cannot_be_changed_or_removed_through_member_endpoint(self) -> None:
        project, _ = self.create_project()
        owner_membership = ProjectMember.objects.get(project=project, user=self.owner)
        url = reverse(
            "projects:project-member-detail", args=(project.pk, owner_membership.pk)
        )

        self.assertEqual(
            self.client.patch(url, {"role": ProjectMember.Role.MEMBER}, format="json").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_400_BAD_REQUEST)

    def test_anonymous_user_is_denied(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_401_UNAUTHORIZED)
