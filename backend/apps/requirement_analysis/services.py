"""Transactional services for requirement-analysis record lifecycle actions."""

from typing import Any

from django.db import transaction

from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.stability import analysis_baseline, count_payload


class RequirementAnalysisRecordService:
    """Handle destructive analysis-record operations without deleting sources."""

    @transaction.atomic
    def clear_records(self, document: RequirementDocument) -> dict[str, Any]:
        """Clear analysis history and reports while preserving the source document.

        Existing case-generation records intentionally remain available as historical
        outputs. The document is reset to an uploaded state so the workbench no longer
        presents cleared analysis as a current result.
        """
        locked_document = RequirementDocument.objects.select_for_update().get(pk=document.pk)
        latest = locked_document.analyses.order_by("-created_at").first()
        baseline = dict(locked_document.analysis_baseline or {})
        if latest is not None:
            latest_baseline = analysis_baseline(
                source_fingerprint=latest.source_fingerprint,
                analysis_fingerprint=latest.analysis_fingerprint,
                quality_status=latest.quality_status,
                counts=count_payload({
                    "modules": latest.modules,
                    "functions": latest.functions,
                    "linkages": latest.linkages,
                    "test_points": latest.test_points,
                }),
            )
            if latest.quality_status == RequirementAnalysis.QualityStatus.COMPLETE or not baseline:
                baseline = latest_baseline
        deleted_count, _ = RequirementAnalysis.objects.filter(document_id=locked_document.pk).delete()
        visual_report_cleared = bool(locked_document.visual_analysis_report)
        locked_document.visual_analysis_report = {}
        locked_document.analysis_baseline = baseline
        locked_document.status = RequirementDocument.Status.UPLOADED
        locked_document.save(update_fields=("visual_analysis_report", "analysis_baseline", "status"))
        return {
            "cleared_analysis_count": deleted_count,
            "visual_report_cleared": visual_report_cleared,
            "document_status": locked_document.status,
            "source_preserved": True,
            "analysis_baseline_preserved": bool(baseline),
            "case_generation_records_preserved": True,
        }


__all__ = ["RequirementAnalysisRecordService"]
