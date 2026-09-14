"""T155 tests for routed requirement and visual analysis lifecycle behavior."""

import base64
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.projects.models import Project
from apps.requirement_analysis.analyzer import analyze_requirement_document
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument


class VisualRuntimeT155Tests(SimpleTestCase):
    """Cover visual schema validation through the shared structured runtime."""

    def test_visual_output_is_validated_and_keeps_evidence_contract(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = {
            "elements": [{"id": "element-1", "text": "登录", "evidence_ids": ["ocr-1"]}],
            "text_blocks": [{"id": "text-1", "text": "登录", "evidence_ids": ["ocr-1"]}],
            "regions": [],
            "test_points": [{"id": "point-1", "description": "确认登录", "evidence_ids": ["ocr-1"]}],
            "confidence": 0.88,
            "warnings": [],
            "needs_confirmation": False,
        }
        manager = Mock()
        manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(name="fake"))
        prompts = Mock()
        prompts.resolve.return_value = SimpleNamespace(content="视觉 JSON")

        result = RequirementModelAdapter(model_manager=manager, prompt_manager=prompts).analyze_visual(
            text="登录",
            evidence=[{"id": "ocr-1", "text": "登录"}],
            image_bytes=b"png",
            image_mime_type="image/png",
        )

        self.assertEqual(result["method"], "model_verified_visual")
        self.assertEqual(result["elements"][0]["evidence_ids"], ["ocr-1"])
        self.assertFalse(result["needs_confirmation"])

    def test_visual_output_rejects_unknown_evidence(self) -> None:
        runtime = Mock()
        runtime.generate_structured.return_value = {
            "elements": [{"id": "element-1", "text": "登录", "evidence_ids": ["unknown"]}],
            "text_blocks": [],
            "regions": [],
            "test_points": [],
        }
        manager = Mock()
        manager.execute_with_fallback.side_effect = lambda _task, operation, **_kwargs: operation(runtime, SimpleNamespace(name="fake"))
        prompts = Mock()
        prompts.resolve.return_value = SimpleNamespace(content="视觉 JSON")

        with self.assertRaises(ModelAnalysisError):
            RequirementModelAdapter(model_manager=manager, prompt_manager=prompts).analyze_visual(
                text="登录",
                evidence=[{"id": "ocr-1", "text": "登录"}],
                image_bytes=b"png",
                image_mime_type="image/png",
            )


class RequirementAnalysisT155Tests(TestCase):
    """Verify model failures and visual calls expose truthful REST state."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.owner = get_user_model().objects.create_user(username="t155-owner")
        self.project = Project.objects.create(name="T155 project", created_by=self.owner)
        self.document = RequirementDocument.objects.create(
            project=self.project,
            title="登录需求",
            content_text="用户登录系统并查看订单。",
            created_by=self.owner,
        )
        self.chat = ModelConfig.objects.create(
            name="t155-chat",
            provider=ModelConfig.Provider.CUSTOM,
            model_name="t155-chat-model",
            model_type=ModelConfig.ModelType.CHAT,
        )
        self.vision = ModelConfig.objects.create(
            name="t155-vision",
            provider=ModelConfig.Provider.CUSTOM,
            model_name="t155-vision-model",
            model_type=ModelConfig.ModelType.VISION,
        )
        self.client.force_authenticate(self.owner)

    def test_fallback_preserves_structured_failure_details(self) -> None:
        runtime = Mock()
        runtime.generate_structured.side_effect = ModelAnalysisError(
            "provider returned invalid JSON",
            code="invalid_response",
            structured_trace=[{"segment_id": "segment-0001", "status": "failed", "error_code": "invalid_response"}],
            partial_payload={"coverage_report": {"structured_generation": {"completed_segments": 0}}},
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
            primary_model=self.chat,
        )
        prompts = Mock()
        prompts.resolve.return_value = SimpleNamespace(content="JSON")
        adapter = RequirementModelAdapter(
            runtime_factory=lambda _config: runtime,
            prompt_manager=prompts,
        )

        with self.assertRaises(ModelAnalysisError) as raised:
            adapter.analyze(text="鐧诲綍", evidence=[{"id": "evidence-1", "text": "鐧诲綍"}])

        self.assertEqual(raised.exception.code, "invalid_response")
        self.assertEqual(raised.exception.structured_trace[0]["segment_id"], "segment-0001")

    def test_model_failure_returns_retryable_partial_state_and_preserves_history(self) -> None:
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
            primary_model=self.chat,
        )
        partial = {
            "modules": [{"id": "module-1", "name": "登录"}],
            "functions": [{"id": "function-1", "name": "登录", "module_id": "module-1"}],
            "linkages": [],
            "test_points": [],
            "coverage_report": {"structured_generation": {"status": "partial", "completed_segments": 1}},
        }
        with patch(
            "apps.requirement_analysis.analyzer.RequirementModelAdapter.analyze",
            side_effect=ModelAnalysisError("供应商暂时不可用", code="provider_http_error", partial_payload=partial),
        ):
            response = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["code"], "provider_http_error")
        self.assertEqual(response.data["status"], "partial")
        self.assertTrue(response.data["retryable"])
        latest = RequirementAnalysis.objects.get(document=self.document)
        self.assertEqual(latest.coverage_report["analysis_method"], "model_partial")
        self.assertEqual(latest.coverage_report["model_status"], "partial")
        self.assertEqual(RequirementDocument.objects.get(pk=self.document.pk).status, RequirementDocument.Status.FAILED)

    def test_verified_analysis_records_route_and_call_stage(self) -> None:
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.REQUIREMENT_ANALYSIS,
            primary_model=self.chat,
        )
        payload = {
            "modules": [{"id": "module-1", "name": "登录"}],
            "functions": [{"id": "function-1", "name": "登录", "module_id": "module-1"}],
            "linkages": [],
            "test_points": [{"id": "point-1", "description": "正常登录"}],
            "coverage_report": {},
        }
        with patch("apps.requirement_analysis.analyzer.RequirementModelAdapter.analyze", return_value=payload):
            response = self.client.post(f"/api/requirement-documents/{self.document.pk}/analyze/", format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        report = response.data["latest_analysis"]["coverage_report"]
        self.assertEqual(report["analysis_method"], "model_verified")
        self.assertEqual(report["model_status"], "verified")
        self.assertEqual(report["call_stage"], "requirement_analysis")
        self.assertEqual(report["model_route"]["candidates"][0]["name"], self.chat.name)

    def test_visual_analysis_uses_vision_route_and_persists_report(self) -> None:
        document = RequirementDocument.objects.create(
            project=self.project,
            title="登录截图",
            source_type=RequirementDocument.SourceType.SCREENSHOT,
            content_text="登录按钮",
            created_by=self.owner,
        )
        ModelRoutingPolicy.objects.create(
            feature_key=ModelRoutingPolicy.FeatureKey.SCREENSHOT_ANALYSIS,
            primary_model=self.vision,
        )
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "login.png"
            path.write_bytes(png)
            document.file_path = str(path)
            document.save(update_fields=("file_path",))
            report = {
                "elements": [{"id": "element-1", "text": "登录", "type": "control", "evidence_ids": []}],
                "text_blocks": [{"id": "text-1", "text": "登录", "evidence_ids": []}],
                "regions": [],
                "test_points": [{"id": "visual-point-1", "description": "确认登录按钮可见", "evidence_ids": []}],
                "confidence": 0.91,
                "needs_confirmation": False,
                "warnings": [],
                "coverage_report": {"structured_generation": {"status": "completed", "segment_count": 1, "completed_segments": 1}},
            }
            with patch("apps.requirement_analysis.views.RequirementModelAdapter.analyze_visual", return_value=report):
                response = self.client.post(f"/api/requirement-documents/{document.pk}/screenshot-analysis/", format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["analysis_method"], "model_verified")
        stored = RequirementDocument.objects.get(pk=document.pk).visual_analysis_report
        self.assertEqual(stored["model_status"], "verified")
        self.assertEqual(stored["call_stage"], "screenshot_analysis")

    def test_visual_analysis_without_file_has_actionable_error(self) -> None:
        document = RequirementDocument.objects.create(
            project=self.project,
            title="OCR截图",
            source_type=RequirementDocument.SourceType.SCREENSHOT,
            content_text="登录按钮",
            created_by=self.owner,
        )
        response = self.client.post(f"/api/requirement-documents/{document.pk}/screenshot-analysis/", format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "image_required")
        self.assertEqual(RequirementDocument.objects.get(pk=document.pk).visual_analysis_report["status"], "failed")
