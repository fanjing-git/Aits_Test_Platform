"""REST endpoints for generation, review and automation selection."""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from uuid import uuid4
from django.conf import settings

from apps.case_generation.generator import CaseGenerationError, generate_document_cases
from apps.case_generation.generator import create_pending_generation_record
from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.reviewer import CaseReviewError, review_generation_record
from apps.case_generation.review_editing import ReviewEditingError, save_reviewed_cases
from apps.case_generation.tasks import run_case_generation, run_case_review
from apps.case_generation.selector import CaseSelectionError, select_generation_record
from apps.case_generation.serializers import CaseGenerationRecordSerializer, ManualReviewCasesSerializer
from apps.projects.permissions import is_platform_admin
from apps.skills.orchestration import SkillExecutionService
from apps.configs.models import ModelConfig, ModelRoutingPolicy
from apps.configs.routing import ModelRouteError, ModelRouteResolver, required_model_types
from apps.configs.serializers import SafeModelSummarySerializer
from apps.requirement_analysis.permissions import RequirementPermission, can_manage_requirements
from core.task_state import task_runtime, utc_now


class CaseGenerationViewSet(viewsets.ModelViewSet):
    """Manage project-scoped generation records through the workbench API."""

    serializer_class = CaseGenerationRecordSerializer
    permission_classes = (RequirementPermission,)
    http_method_names = ("get", "post", "delete", "head", "options")

    def destroy(self, request, *args, **kwargs):
        """Delete one generation record within the user's project boundary."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能删除用例生成记录。")
        self.perform_destroy(record)
        return Response(status=204)

    def get_queryset(self):
        """Return only records in projects visible to the current user."""
        queryset = CaseGenerationRecord.objects.select_related("project", "document")
        if not is_platform_admin(self.request.user):
            queryset = queryset.filter(project__memberships__user=self.request.user) | queryset.filter(project__created_by=self.request.user)
        project = self.request.query_params.get("project")
        if project:
            queryset = queryset.filter(project_id=project)
        document = self.request.query_params.get("document")
        if document:
            queryset = queryset.filter(document_id=document)
        return queryset.distinct()

    @staticmethod
    def _preferred_model_name(request, feature_key: str) -> str | None:
        """Validate an optional per-run model choice against feature capability."""
        raw_id = request.data.get("model_config_id")
        if raw_id in (None, "", "null"):
            return None
        try:
            config_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"model_config_id": "模型配置编号无效。"}) from exc
        config = ModelConfig.objects.filter(pk=config_id, is_active=True).first()
        if config is None or config.model_type not in set(required_model_types(feature_key)):
            raise ValidationError({"model_config_id": "所选模型不存在、已停用或不支持此功能。"})
        return config.name

    @action(detail=False, methods=("get",), url_path="model-options")
    def model_options(self, request):
        """Return safe selectable models and the effective route for generation or review."""
        feature = request.query_params.get("feature", ModelRoutingPolicy.FeatureKey.CASE_GENERATION)
        if feature not in {ModelRoutingPolicy.FeatureKey.CASE_GENERATION, ModelRoutingPolicy.FeatureKey.CASE_REVIEW}:
            raise ValidationError({"feature": "功能必须是用例生成或用例评审。"})
        required = required_model_types(feature)
        models = ModelConfig.objects.filter(is_active=True, model_type__in=required).order_by("priority", "name")
        try:
            route = ModelRouteResolver().resolve(feature)
            effective = route.primary.config if route.primary else None
            effective_source = route.primary.source if route.primary else ""
            route_error = route.failure_reason
            route_diagnostics = route.as_dict()
        except ModelRouteError as exc:
            effective = None
            effective_source = ""
            route_error = str(exc)
            route_diagnostics = {"available": False, "failure_reason": route_error}
        return Response({
            "feature_key": feature,
            "required_model_types": list(required),
            "models": SafeModelSummarySerializer(models, many=True).data,
            "effective_model": SafeModelSummarySerializer(effective).data if effective else None,
            "effective_source": effective_source,
            "route_error": route_error,
            "route": route_diagnostics,
        })

    def create(self, request, *args, **kwargs):
        """Generate a new five-round record from the latest document analysis."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.validated_data["document"]
        reviewed_test_point_ids = serializer.validated_data.get("reviewed_test_point_ids")
        if not can_manage_requirements(request.user, document.project):
            raise PermissionDenied("当前项目角色不能生成测试用例。")
        try:
            preferred_model_name = self._preferred_model_name(request, ModelRoutingPolicy.FeatureKey.CASE_GENERATION)
            if not settings.CELERY_TASK_ALWAYS_EAGER:
                record = create_pending_generation_record(document, reviewed_test_point_ids=reviewed_test_point_ids)
                task_id = uuid4().hex
                runtime = task_runtime(task_id, "case_generation", status="pending", current_step="排队中", result_id=str(record.pk))
                record.coverage_report = {**record.coverage_report, "task_runtime": runtime}
                record.save(update_fields=("coverage_report",))
                try:
                    run_case_generation.apply_async(args=[str(record.pk), preferred_model_name, task_id], task_id=task_id)
                except Exception:
                    runtime.update({"status": "failed", "error_code": "task_enqueue_failed", "updated_at": utc_now()})
                    record.coverage_report = {**record.coverage_report, "task_runtime": runtime, "execution_status": "failed"}
                    record.status = CaseGenerationRecord.Status.FAILED
                    record.save(update_fields=("coverage_report", "status"))
                    return Response({"detail": "用例生成任务提交失败，请稍后重试。", "code": "task_enqueue_failed"}, status=503)
                return Response({**self.get_serializer(record).data, "task_runtime": runtime}, status=202)
            record = generate_document_cases(
                document,
                preferred_model_name=preferred_model_name,
                reviewed_test_point_ids=reviewed_test_point_ids,
            )
        except CaseGenerationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        skill = SkillExecutionService().execute(
            "case_gen",
            {"user_input": document.content_text or document.title, "project_id": str(document.project_id)},
        )
        data = self.get_serializer(record).data
        data["skill_execution"] = skill.as_dict() if skill else None
        return Response(data, status=201)

    @action(detail=True, methods=("post",))
    def review(self, request, pk=None):
        """Run and persist the five-round case review."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能评审测试用例。")
        if record.review_rounds >= 5 and isinstance(record.review_report, dict) and "approved" in record.review_report:
            return Response(self.get_serializer(record).data)
        try:
            preferred_model_name = self._preferred_model_name(request, ModelRoutingPolicy.FeatureKey.CASE_REVIEW)
            current_runtime = dict((record.review_report or {}).get("task_runtime") or {}) if isinstance(record.review_report, dict) else {}
            if current_runtime.get("status") in {"pending", "running", "cancel_requested"}:
                return Response({"detail": "当前评审任务仍在处理中，请等待完成或先取消。", "task_runtime": current_runtime}, status=409)
            if not settings.CELERY_TASK_ALWAYS_EAGER:
                task_id = uuid4().hex
                runtime = task_runtime(task_id, "case_review", status="pending", current_step="排队中", result_id=str(record.pk))
                record.review_report = {**(record.review_report or {}), "task_runtime": runtime, "execution_status": "running"}
                record.status = CaseGenerationRecord.Status.REVIEWING
                record.save(update_fields=("review_report", "status"))
                try:
                    run_case_review.apply_async(args=[str(record.pk), preferred_model_name, task_id], task_id=task_id)
                except Exception:
                    runtime.update({"status": "failed", "error_code": "task_enqueue_failed", "updated_at": utc_now()})
                    record.review_report = {**record.review_report, "task_runtime": runtime, "execution_status": "failed"}
                    record.status = CaseGenerationRecord.Status.FAILED
                    record.save(update_fields=("review_report", "status"))
                    return Response({"detail": "用例评审任务提交失败，请稍后重试。", "code": "task_enqueue_failed"}, status=503)
                return Response({**self.get_serializer(record).data, "task_runtime": runtime}, status=202)
            record = review_generation_record(record, preferred_model_name=preferred_model_name)
        except CaseReviewError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        skill = SkillExecutionService().execute(
            "case_review",
            {"user_input": record.document.content_text or record.document.title, "cases": record.cases, "project_id": str(record.project_id)},
        )
        data = self.get_serializer(record).data
        data["skill_execution"] = skill.as_dict() if skill else None
        return Response(data)

    @action(detail=True, methods=("post",), url_path="cancel")
    def cancel(self, request, pk=None):
        """Request cooperative cancellation of generation or review work."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能取消用例处理任务。")
        report_name = "review_report" if record.status == CaseGenerationRecord.Status.REVIEWING else "coverage_report"
        report = dict(getattr(record, report_name, {}) or {})
        runtime = dict(report.get("task_runtime") or {})
        if runtime.get("status") not in {"pending", "running", "cancel_requested"}:
            raise ValidationError({"detail": "当前没有可取消的后台任务。"})
        runtime.update({"status": "cancel_requested", "cancel_requested": True, "current_step": "正在取消", "updated_at": utc_now()})
        report["task_runtime"] = runtime
        setattr(record, report_name, report)
        record.save(update_fields=(report_name,))
        if runtime.get("task_id"):
            try:
                from config.celery_app import app
                app.control.revoke(str(runtime["task_id"]), terminate=False)
            except Exception:
                pass
        return Response({"task_runtime": runtime, "record": self.get_serializer(record).data})

    @action(detail=True, methods=("post",))
    def select(self, request, pk=None):
        """Persist automation suitability and aggregate counts."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能筛选测试用例。")
        if isinstance(record.coverage_report, dict) and isinstance(record.coverage_report.get("automation_selection"), dict):
            return Response(self.get_serializer(record).data)
        try:
            record = select_generation_record(record)
        except CaseSelectionError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(record).data)

    @action(detail=True, methods=("post",), url_path="review-cases")
    def review_cases(self, request, pk=None):
        """Save confirmed manual corrections and additions for a new review."""
        record = self.get_object()
        if not can_manage_requirements(request.user, record.project):
            raise PermissionDenied("当前项目角色不能修改评审用例。")
        serializer = ManualReviewCasesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            record = save_reviewed_cases(
                record,
                serializer.validated_data.get("cases", []),
                serializer.validated_data.get("new_cases", []),
            )
        except ReviewEditingError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(record).data)
