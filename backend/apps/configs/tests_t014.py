"""Prompt configuration REST API tests for task T014."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.configs.models import PromptConfig
from apps.users.models import UserProfile


class PromptConfigApiTests(APITestCase):
    def setUp(self) -> None:
        PromptConfig.objects.all().delete()
        self.admin = get_user_model().objects.create_user(username="prompt-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = get_user_model().objects.create_user(username="prompt-viewer")
        self.client.force_authenticate(self.admin)
        self.list_url = reverse("configs:prompt-config-list")

    def payload(self) -> dict[str, object]:
        return {
            "name": "api-template",
            "scope": PromptConfig.Scope.SCENE,
            "scene_type": PromptConfig.SceneType.API_TEST,
            "content": "Test {{ method }} {{ path }}",
            "variables": {"method": "GET"},
            "is_active": True,
        }

    def test_admin_can_create_list_update_and_delete_prompt(self) -> None:
        created = self.client.post(self.list_url, self.payload(), format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["version"], 1)
        detail = reverse("configs:prompt-config-detail", args=(created.data["id"],))

        updated = self.client.patch(detail, {"content": "Updated"}, format="json")
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["version"], 2)
        self.assertFalse(PromptConfig.objects.get(pk=created.data["id"]).is_active)

        listed = self.client.get(self.list_url)
        self.assertEqual(len(listed.data), 1)
        self.assertEqual(listed.data[0]["version"], 2)

        new_detail = reverse("configs:prompt-config-detail", args=(updated.data["id"],))
        self.assertEqual(self.client.delete(new_detail).status_code, status.HTTP_204_NO_CONTENT)

    def test_history_and_rollback_create_a_new_auditable_version(self) -> None:
        created = self.client.post(self.list_url, self.payload(), format="json")
        detail = reverse("configs:prompt-config-detail", args=(created.data["id"],))
        updated = self.client.patch(detail, {"content": "second"}, format="json")
        history_url = reverse("configs:prompt-config-history", args=(updated.data["id"],))

        history = self.client.get(history_url)
        self.assertEqual([item["version"] for item in history.data], [2, 1])

        rollback_url = reverse("configs:prompt-config-rollback", args=(updated.data["id"],))
        rolled_back = self.client.post(rollback_url, {"version": 1}, format="json")
        self.assertEqual(rolled_back.status_code, status.HTTP_201_CREATED)
        self.assertEqual(rolled_back.data["version"], 3)
        self.assertEqual(rolled_back.data["content"], self.payload()["content"])

    def test_preview_renders_variables_and_reports_missing_values(self) -> None:
        created = self.client.post(self.list_url, self.payload(), format="json")
        preview_url = reverse("configs:prompt-config-preview", args=(created.data["id"],))

        missing = self.client.post(preview_url, {}, format="json")
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("path", missing.data["variables"][0])

        rendered = self.client.post(
            preview_url, {"variables": {"path": "/health/"}}, format="json"
        )
        self.assertEqual(rendered.status_code, status.HTTP_200_OK)
        self.assertEqual(rendered.data["rendered_content"], "Test GET /health/")

    def test_invalid_history_version_is_rejected_without_state_change(self) -> None:
        created = self.client.post(self.list_url, self.payload(), format="json")
        rollback_url = reverse("configs:prompt-config-rollback", args=(created.data["id"],))

        response = self.client.post(rollback_url, {"version": 99}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PromptConfig.objects.count(), 1)

    def test_non_admin_and_anonymous_users_are_denied(self) -> None:
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_401_UNAUTHORIZED)
