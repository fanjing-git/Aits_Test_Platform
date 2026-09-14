"""T158 embedding capability gates and explicit offline compatibility tests."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.knowledge.models import Document, Embedding, KnowledgeBase
from apps.knowledge.retrieval import HashVectorizer
from apps.knowledge.embedding_policy import EmbeddingPolicyService
from apps.projects.models import Project, ProjectMember


class EmbeddingPolicyServiceTests(TestCase):
    """Verify route diagnostics and production/offline mode separation."""

    def test_missing_route_is_actionable_and_offline_mode_is_explicit(self) -> None:
        policy = EmbeddingPolicyService().describe()
        self.assertFalse(policy["available"])
        self.assertEqual(policy["code"], "embedding_route_unavailable")
        with override_settings(DEBUG=True):
            execution = EmbeddingPolicyService().prepare("offline_test")
        self.assertEqual(execution.metadata["embedding_mode"], "offline_test")
        self.assertIsInstance(execution.vectorizer, HashVectorizer)

    def test_incompatible_route_is_not_treated_as_embedding(self) -> None:
        model = ModelConfig.objects.create(
            name="T158 chat only",
            provider=ModelConfig.Provider.LOCAL,
            model_name="chat",
            model_type=ModelConfig.ModelType.CHAT,
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.KNOWLEDGE_MODEL,
            primary_model=model,
        )
        policy = EmbeddingPolicyService().describe()
        self.assertFalse(policy["available"])
        self.assertEqual(policy["code"], "model_capability_mismatch")


class EmbeddingPolicyAPITests(APITestCase):
    """Cover REST status, provider blocking and explicit offline compatibility."""

    def setUp(self) -> None:
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="t158-owner")
        self.viewer = user_model.objects.create_user(username="t158-viewer")
        self.project = Project.objects.create(name="T158 project", created_by=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.owner, role="owner")
        ProjectMember.objects.create(project=self.project, user=self.viewer, role="viewer")
        self.base = KnowledgeBase.objects.create(
            name="T158 knowledge", project=self.project, created_by=self.owner
        )
        self.document = Document.objects.create(
            knowledge_base=self.base,
            title="T158 guide",
            source_type=Document.SourceType.MANUAL,
            content_text="login requires an approved token",
            status=Document.Status.READY,
            created_by=self.owner,
        )
        Embedding.objects.create(
            knowledge_base=self.base,
            document=self.document,
            content=self.document.content_text,
        )
        self.client.force_authenticate(self.owner)

    def test_policy_endpoint_is_safe_without_route(self) -> None:
        response = self.client.get("/api/knowledge-search/policy/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["available"])
        self.assertEqual(response.data["code"], "embedding_route_unavailable")
        self.assertNotIn("api_key", str(response.data).lower())

    def test_provider_index_is_blocked_without_embedding_runtime(self) -> None:
        response = self.client.post(f"/api/knowledge-documents/{self.document.pk}/index/", {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "embedding_route_unavailable")
        self.document.refresh_from_db()
        self.assertIsNone(self.document.embeddings.first().vector)

    @override_settings(DEBUG=True)
    def test_offline_index_requires_explicit_mode_and_is_marked(self) -> None:
        response = self.client.post(
            f"/api/knowledge-documents/{self.document.pk}/index/",
            {"mode": "offline_test"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["metadata"]["embedding_mode"], "offline_test")
        self.assertEqual(response.data["metadata"]["embedding_model"], "local-hash-v1")

        self.document.review_status = "approved"
        self.document.reviewed_by = self.owner
        self.document.save(update_fields=("review_status", "reviewed_by"))

        search = self.client.post(
            "/api/knowledge-search/",
            {
                "query": "approved token",
                "knowledge_base_ids": [str(self.base.pk)],
                "mode": "offline_test",
            },
            format="json",
        )
        self.assertEqual(search.status_code, 200, search.data)
        self.assertTrue(search.data["results"])
        self.assertEqual(search.data["embedding_policy"]["embedding_mode"], "offline_test")

    def test_policy_and_index_keep_authentication_and_management_boundaries(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/knowledge-search/policy/").status_code, 401)
        self.client.force_authenticate(self.viewer)
        response = self.client.post(
            f"/api/knowledge-documents/{self.document.pk}/index/",
            {"mode": "offline_test"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
