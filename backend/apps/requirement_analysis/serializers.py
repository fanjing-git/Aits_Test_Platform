"""REST serializers for requirement documents and analysis results."""

from pathlib import Path
from uuid import uuid4

from django.conf import settings
from rest_framework import serializers

from apps.projects.models import Project
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument


class RequirementAnalysisSerializer(serializers.ModelSerializer):
    """Expose structured analysis without server file paths or secrets."""

    document_title = serializers.CharField(source="document.title", read_only=True)

    class Meta:
        model = RequirementAnalysis
        fields = (
            "id", "document", "document_title", "modules", "functions", "linkages",
            "test_points", "coverage_report", "created_at",
        )
        read_only_fields = fields


class RequirementDocumentSerializer(serializers.ModelSerializer):
    """Accept safe metadata and an optional bounded upload."""

    project_name = serializers.CharField(source="project.name", read_only=True)
    source_type_label = serializers.CharField(source="get_source_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    latest_analysis = serializers.SerializerMethodField()
    file = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = RequirementDocument
        fields = (
            "id", "project", "project_name", "title", "version", "source_type",
            "source_type_label", "source_url", "content_text", "status", "status_label",
            "parse_evidence", "parse_confidence", "parse_warnings", "latest_analysis", "file", "created_by", "created_at",
        )
        read_only_fields = ("id", "status", "status_label", "latest_analysis", "created_by", "created_at")
        extra_kwargs = {"content_text": {"required": False, "allow_blank": True}}

    def get_latest_analysis(self, obj):
        """Return the newest analysis result for the document, if available."""
        analysis = obj.analyses.order_by("-created_at").first()
        return RequirementAnalysisSerializer(analysis).data if analysis else None

    def validate_project(self, value: Project):
        """Require the caller to belong to the selected project."""
        user = self.context["request"].user
        if getattr(user.profile, "role", None) == "admin":
            return value
        if not value.memberships.filter(user=user).exists() and value.created_by_id != user.pk:
            raise serializers.ValidationError("项目不存在或不可访问。")
        return value

    def validate(self, attrs):
        """Enforce source-specific fields before writing any file."""
        source_type = attrs.get("source_type", getattr(self.instance, "source_type", RequirementDocument.SourceType.MANUAL))
        upload = attrs.get("file")
        content = str(attrs.get("content_text", getattr(self.instance, "content_text", "")) or "").strip()
        source_url = str(attrs.get("source_url", getattr(self.instance, "source_url", "")) or "").strip()
        if source_type == RequirementDocument.SourceType.ONLINE_LINK and not source_url:
            raise serializers.ValidationError({"source_url": "在线链接必须提供来源地址。"})
        if source_type == RequirementDocument.SourceType.MANUAL and not content:
            raise serializers.ValidationError({"content_text": "手工录入内容不能为空。"})
        if source_type == RequirementDocument.SourceType.FILE and not upload and not getattr(self.instance, "file_path", ""):
            raise serializers.ValidationError({"file": "文件来源必须上传文件。"})
        if source_type == RequirementDocument.SourceType.SCREENSHOT and not upload and not getattr(self.instance, "file_path", "") and not content:
            raise serializers.ValidationError({"file": "截图来源必须上传图片或提供 OCR 正文。"})
        if upload:
            suffix = Path(upload.name or "").suffix.casefold()
            allowed = {".txt", ".md", ".markdown", ".pdf", ".docx", ".xlsx", ".json", ".png", ".jpg", ".jpeg", ".webp"}
            if suffix not in allowed:
                raise serializers.ValidationError({"file": "仅支持 PDF、Word、Excel、Markdown、Swagger、文本和图片文件。"})
            if upload.size > settings.REQUIREMENT_DOCUMENT_MAX_BYTES:
                raise serializers.ValidationError({"file": "文件超过10MB限制。"})
        return attrs

    def create(self, validated_data):
        """Store uploads under a generated name and assign the creator."""
        upload = validated_data.pop("file", None)
        if upload:
            root = Path(settings.REQUIREMENT_DOCUMENT_ROOT)
            root.mkdir(parents=True, exist_ok=True)
            target = root / f"{uuid4().hex}{Path(upload.name).suffix.casefold()}"
            with target.open("wb") as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
            validated_data["file_path"] = str(target)
        return RequirementDocument.objects.create(created_by=self.context["request"].user, **validated_data)
