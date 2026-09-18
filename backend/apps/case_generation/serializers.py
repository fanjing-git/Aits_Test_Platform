"""REST serializers for generated test case records."""

from rest_framework import serializers

from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.llm_adapter import REVIEW_SEVERITY_LABELS, _localize_review_text
from apps.requirement_analysis.models import RequirementDocument


class ManualReviewCaseSerializer(serializers.Serializer):
    """Validate editable fields for an existing or manually added case."""

    id = serializers.CharField(required=False, allow_blank=False)
    title = serializers.CharField(required=False, allow_blank=False)
    steps = serializers.ListField(child=serializers.CharField(), required=False)
    expected_result = serializers.CharField(required=False, allow_blank=False)
    priority = serializers.CharField(required=False, allow_blank=False)
    automatable = serializers.BooleanField(required=False)
    type = serializers.CharField(required=False, allow_blank=False)
    test_design_method = serializers.CharField(required=False, allow_blank=False)
    source_function_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    source_module_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    source_test_point_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    evidence_ids = serializers.ListField(child=serializers.CharField(), required=False)


class ManualReviewCasesSerializer(serializers.Serializer):
    """Validate a confirmed batch of manual case corrections and additions."""

    cases = ManualReviewCaseSerializer(many=True, required=False, default=list)
    new_cases = ManualReviewCaseSerializer(many=True, required=False, default=list)

    def validate_cases(self, value: list[dict]) -> list[dict]:
        """Require IDs for updates to existing cases."""
        missing = [index + 1 for index, item in enumerate(value) if not item.get("id")]
        if missing:
            raise serializers.ValidationError(f"第 {missing[0]} 条修订用例缺少用例编号。")
        return value


class CaseGenerationRecordSerializer(serializers.ModelSerializer):
    """Expose generated cases and review metadata without internal paths."""

    document_title = serializers.CharField(source="document.title", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    review_report = serializers.SerializerMethodField()
    reviewed_test_point_ids = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False, default=None, allow_null=True,
    )

    class Meta:
        model = CaseGenerationRecord
        fields = (
            "id", "project", "project_name", "document", "document_title", "rounds",
            "total_cases", "auto_cases", "manual_cases", "cases", "coverage_report",
            "review_rounds", "review_report", "status", "created_at", "reviewed_test_point_ids",
        )
        read_only_fields = (
            "id", "project", "project_name", "document_title", "rounds", "total_cases",
            "auto_cases", "manual_cases", "cases", "coverage_report", "review_rounds",
            "review_report", "status", "created_at",
        )

    def get_review_report(self, obj: CaseGenerationRecord) -> dict:
        """Return review data with legacy model English normalized for display."""
        if self._is_abandoned_empty_generation(obj):
            return {
                "approved": False,
                "case_count": 0,
                "issue_count": 0,
                "round_trace": [],
                "analysis_method": "not_applicable",
                "execution_status": "skipped",
                "skipped": True,
                "message": "本次没有生成任何用例，暂无用例可评审。",
            }
        if obj.status == CaseGenerationRecord.Status.REVIEWING and not any(isinstance(item, dict) for item in (obj.cases or [])):
            return {
                "approved": False,
                "case_count": 0,
                "issue_count": 0,
                "round_trace": [],
                "analysis_method": "not_applicable",
                "execution_status": "skipped",
                "skipped": True,
                "message": "当前记录没有可评审的用例。",
            }
        report = dict(obj.review_report) if isinstance(obj.review_report, dict) else {}
        issues = report.get("issues")
        if not isinstance(issues, list):
            return report
        normalized: list[dict] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(issues, start=1):
            if not isinstance(raw, dict):
                continue
            issue = dict(raw)
            description = str(issue.get("description", "")).strip()
            suggestion = str(issue.get("suggestion", "")).strip()
            if description and "model_description" not in issue:
                issue["model_description"] = description
            if suggestion and "model_suggestion" not in issue:
                issue["model_suggestion"] = suggestion
            issue["description"] = _localize_review_text(description)
            issue["suggestion"] = _localize_review_text(suggestion, suggestion=True)
            severity = str(issue.get("severity", "medium")).strip().lower()
            issue["severity"] = severity
            issue["severity_label"] = REVIEW_SEVERITY_LABELS.get(severity, "中")
            issue_id = str(issue.get("id") or "").strip()
            if not issue_id or issue_id in seen_ids:
                issue_id = f"review-issue-{index}"
            seen_ids.add(issue_id)
            issue["id"] = issue_id
            normalized.append(issue)
        report["issues"] = normalized
        return report

    @staticmethod
    def _is_abandoned_empty_generation(obj: CaseGenerationRecord) -> bool:
        """Identify an initial generation shell left without any execution result."""
        return (
            obj.status == CaseGenerationRecord.Status.GENERATING
            and not obj.cases
            and obj.rounds == 0
            and obj.total_cases == 0
            and not obj.coverage_report
            and not obj.review_report
        )

    def to_representation(self, instance: CaseGenerationRecord) -> dict:
        """Expose stale empty-review records as finished skipped records."""
        data = super().to_representation(instance)
        if self._is_abandoned_empty_generation(instance):
            data["status"] = CaseGenerationRecord.Status.FAILED
            data["coverage_report"] = {
                "generation_status": "failed",
                "execution_status": "failed",
                "case_count": 0,
                "message": "本次没有生成任何用例，请重新生成。",
            }
        elif instance.status == CaseGenerationRecord.Status.REVIEWING and not any(isinstance(item, dict) for item in (instance.cases or [])):
            data["status"] = CaseGenerationRecord.Status.COMPLETED
            data["review_rounds"] = 0
        return data

    def validate_document(self, value: RequirementDocument) -> RequirementDocument:
        """Ensure the selected document is visible to the authenticated user."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("请先登录。")
        from apps.projects.permissions import is_platform_admin, project_role
        if not is_platform_admin(user) and not project_role(user, value.project) and value.project.created_by_id != user.pk:
            raise serializers.ValidationError("需求文档不存在或不可访问。")
        return value
