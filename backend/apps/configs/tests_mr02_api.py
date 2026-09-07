"""REST contract tests for MR-02 model route configuration."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.users.models import UserProfile


class ModelRoutingPolicyApiTests(APITestCase):
    """Verify administrator route policy CRUD, matrix data, and capability errors."""

    def setUp(self) -> None:
        self.admin = get_user_model().objects.create_user(username="route-admin")
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save(update_fields=("role",))
        self.viewer = get_user_model().objects.create_user(username="route-viewer")
        self.client.force_authenticate(self.admin)
        self.url = reverse("configs:routing-policy-list")
        self.primary = ModelConfig.objects.create(
            name="route-primary",
            provider=ModelConfig.Provider.LOCAL,
            model_name="local-chat",
            model_type=ModelConfig.ModelType.CHAT,
            priority=10,
        )
        self.vision = ModelConfig.objects.create(
            name="route-vision",
            provider=ModelConfig.Provider.LOCAL,
            model_name="local-vision",
            model_type=ModelConfig.ModelType.VISION,
            priority=20,
        )

    def test_admin_can_upsert_and_read_complete_matrix(self) -> None:
        response = self.client.post(
            f"{self.url}upsert/",
            {
                "feature_key": ModelRoutingPolicy.FeatureKey.GLOBAL,
                "primary_model_id": self.primary.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        matrix = self.client.get(f"{self.url}matrix/")
        self.assertEqual(matrix.status_code, status.HTTP_200_OK)
        global_row = next(row for row in matrix.data if row["feature_key"] == "global")
        requirement_row = next(
            row for row in matrix.data if row["feature_key"] == "requirement_analysis"
        )
        self.assertEqual(global_row["effective_model"]["id"], self.primary.pk)
        self.assertEqual(requirement_row["effective_model"]["id"], self.primary.pk)
        self.assertEqual(requirement_row["effective_source"], "global")
        self.assertTrue(requirement_row["inherits_global"])
        self.assertTrue(all("api_key" not in model for model in global_row["available_models"]))

    def test_feature_policy_overrides_global_and_incompatible_model_is_rejected(self) -> None:
        self.client.post(
            f"{self.url}upsert/",
            {
                "feature_key": ModelRoutingPolicy.FeatureKey.GLOBAL,
                "primary_model_id": self.primary.pk,
            },
            format="json",
        )
        feature = self.client.post(
            f"{self.url}upsert/",
            {
                "feature_key": ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS,
                "primary_model_id": self.vision.pk,
            },
            format="json",
        )
        self.assertEqual(feature.status_code, status.HTTP_201_CREATED)
        invalid = self.client.post(
            f"{self.url}upsert/",
            {
                "feature_key": ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS,
                "primary_model_id": self.primary.pk,
            },
            format="json",
        )
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("primary_model_id", invalid.data)

    def test_route_policies_are_admin_only(self) -> None:
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

