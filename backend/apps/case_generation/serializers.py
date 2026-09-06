"""REST serializers for generated test case records."""

from rest_framework import serializers

from apps.case_generation.models import CaseGenerationRecord
from apps.requirement_analysis.models import RequirementDocument


class CaseGenerationRecordSerializer(serializers.ModelSerializer):
    """Expose generated cases and review metadata without internal paths."""

    document_title = serializers.CharField(source="document.title", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)

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
