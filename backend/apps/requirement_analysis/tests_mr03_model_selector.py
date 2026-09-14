"""Focused tests for MR-03 requirement model selection."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import RequirementAnalysisError, analyze_requirement_document
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from core.llm.manager import ModelFallbackExhausted


class RequirementModelSelectorTests(TestCase):
    """Verify model options and per-run selection are project-scoped and validated."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.owner = get_user_model().objects.create_user(username="mr03-owner")
        self.project = Project.objects.create(name="MR03 project", created_by=self.owner)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="需求",
            content_text="用户登录并查看订单。",
            created_by=self.owner,
        )
        self.chat = ModelConfig.objects.create(
            name="mr03-chat",
            provider=ModelConfig.Provider.LOCAL,
            model_name="local-chat",
            model_type=ModelConfig.ModelType.CHAT,
        )
        self.embedding = ModelConfig.objects.create(
            name="mr03-embedding",
            provider=ModelConfig.Provider.LOCAL,
            model_name="local-embedding",
            model_type=ModelConfig.ModelType.EMBEDDING,
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.GLOBAL,
            primary_model=self.chat,
        )
        self.client.force_authenticate(self.owner)
        self.url = f"/api/requirement-documents/{self.document.pk}/"

    def test_options_return_compatible_models_and_global_effective_source(self) -> None:
        response = self.client.get(f"{self.url}model-options/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["effective_source"], "global")
        self.assertEqual(response.data["effective_model"]["id"], self.chat.pk)
        self.assertEqual([item["id"] for item in response.data["models"]], [self.chat.pk])

    def test_analyze_rejects_incompatible_per_run_model(self) -> None:
        response = self.client.post(
            f"{self.url}analyze/",
            {"model_config_id": self.embedding.pk},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("model_config_id", response.data)

    def test_analyze_passes_valid_per_run_model_to_service(self) -> None:
        analysis = RequirementAnalysis.objects.create(
            document=self.document,
            modules=[],
            functions=[],
            linkages=[],
            test_points=[],
            coverage_report={},
        )
        with patch(
            "apps.requirement_analysis.views.analyze_requirement_document",
            return_value=analysis,
        ) as mocked:
            response = self.client.post(
                f"{self.url}analyze/",
                {"model_config_id": self.chat.pk},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mocked.call_args.kwargs["preferred_model_name"], self.chat.name)

    def test_configured_model_failure_never_persists_deterministic_substitute(self) -> None:
        with patch(
            "apps.requirement_analysis.analyzer.RequirementModelAdapter.analyze",
            side_effect=ModelAnalysisError("provider unavailable"),
        ):
            with self.assertRaises(RequirementAnalysisError) as raised:
                analyze_requirement_document(self.document)

        self.assertIn("需求分析模型调用失败：provider unavailable", str(raised.exception))
        self.assertNotIn("已使用确定性基线", str(raised.exception))
        self.assertEqual(self.document.analyses.count(), 1)
        self.assertEqual(self.document.analyses.first().quality_status, RequirementAnalysis.QualityStatus.FAILED)
        self.assertEqual(RequirementDocument.objects.get(pk=self.document.pk).status, RequirementDocument.Status.FAILED)

    def test_model_route_failure_reports_attempted_model_and_network_cause(self) -> None:
        class FailingManager:
            """Simulate a routed provider failure without touching a real network."""

            def execute_with_fallback(self, *args, **kwargs):
                try:
                    raise ModelAnalysisError(
                        "本机网络策略拒绝了 Django/Python 的外网连接（WinError 10013）。"
                    )
                except ModelAnalysisError as cause:
                    raise ModelFallbackExhausted(("mr03-chat",)) from cause

        prompt_manager = SimpleNamespace(
            resolve=lambda *args, **kwargs: SimpleNamespace(content="test prompt")
        )
        adapter = RequirementModelAdapter(
            model_manager=FailingManager(),
            prompt_manager=prompt_manager,
        )

        with self.assertRaises(ModelAnalysisError) as raised:
            adapter.run(text="test", evidence=[])

        message = str(raised.exception)
        self.assertIn("已尝试模型：mr03-chat", message)
        self.assertIn("WinError 10013", message)
        self.assertNotIn("确定性基线", message)
