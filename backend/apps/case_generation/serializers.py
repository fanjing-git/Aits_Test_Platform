"""REST serializers for generated test case records."""

from rest_framework import serializers

from apps.case_generation.models import CaseGenerationRecord
from apps.case_generation.llm_adapter import REVIEW_SEVERITY_LABELS, _localize_review_text
from apps.requirement_analysis.models import RequirementDocument


class CaseGenerationRecordSerializer(serializers.ModelSerializer):
    """Expose generated cases and review metadata without internal paths."""

    document_title = serializers.CharField(source="document.title", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    review_report = serializers.SerializerMethodField()

    class Meta:
        model = CaseGenerationRecord
        fields = (
            "id", "project", "project_name", "document", "document_title", "rounds",
            "total_cases", "auto_cases", "manual_cases", "cases", "coverage_report",
            "review_rounds", "review_report", "status", "created_at",
        )
        read_only_fields = (
            "id", "project", "project_name", "document_title", "rounds", "total_cases",
            "auto_cases", "manual_cases", "cases", "coverage_report", "review_rounds",
            "review_report", "status", "created_at",
        )

    def get_review_report(self, obj: CaseGenerationRecord) -> dict:
        """Return review data with legacy model English normalized for display."""
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
