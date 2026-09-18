"""Transactional services for requirement-analysis record lifecycle actions."""

from typing import Any

from django.db import transaction

from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument
from apps.requirement_analysis.stability import analysis_baseline, analysis_mapping_gaps, analysis_review_state, count_payload


class RequirementAnalysisConfirmationError(ValueError):
    """Raised when a requirement analysis cannot be manually confirmed."""


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

    @transaction.atomic
    def confirm_analysis(
        self,
        document: RequirementDocument,
        user: Any,
        *,
        reviewed_test_point_ids: list[str] | None = None,
        reviewed_evidence_ids: list[str] | None = None,
        reviewed_analysis_item_ids: list[str] | None = None,
        reviewed_conflict_ids: list[str] | None = None,
    ) -> RequirementDocument:
        """Mark a reviewable analysis confirmed only after its checklist is reviewed."""
        locked_document = RequirementDocument.objects.select_for_update().get(pk=document.pk)
        analysis = locked_document.analyses.select_for_update().order_by("-created_at").first()
        if analysis is None:
            raise RequirementAnalysisConfirmationError("需求文档尚未完成需求分析。")
        if analysis.quality_status in {
            RequirementAnalysis.QualityStatus.PARTIAL,
            RequirementAnalysis.QualityStatus.FAILED,
        }:
            raise RequirementAnalysisConfirmationError("当前分析仍未完成，不能确认；请重新执行需求分析。")
        mapping_gaps = analysis_mapping_gaps({
            "modules": analysis.modules,
            "functions": analysis.functions,
            "linkages": analysis.linkages,
            "test_points": analysis.test_points,
        })
        if mapping_gaps:
            gap_count = sum(len(values) for values in mapping_gaps.values())
            raise RequirementAnalysisConfirmationError(
                f"当前分析有{gap_count}项结构或分类信息缺失（模块→功能点→测试点及测试类型），不能确认；请重新执行深度分析。"
            )
        report = dict(analysis.coverage_report or {})
        reviewed = {
            "test_points": {str(value) for value in (reviewed_test_point_ids or [])},
            "evidence": {str(value) for value in (reviewed_evidence_ids or [])},
            "analysis_items": {str(value) for value in (reviewed_analysis_item_ids or [])},
            "conflicts": {str(value) for value in (reviewed_conflict_ids or [])},
        }
        expected_test_points = {
            str(item.get("id")) for item in (analysis.test_points or [])
            if isinstance(item, dict) and item.get("id")
        }
        evidence_coverage = report.get("evidence_coverage") if isinstance(report.get("evidence_coverage"), dict) else {}
        expected_evidence = {str(value) for value in evidence_coverage.get("uncovered_evidence_ids", []) if value}
        expected_analysis_items = {
            str(item.get("id"))
            for key in ("modules", "functions", "linkages", "test_points")
            for item in (getattr(analysis, key) or [])
            if isinstance(item, dict) and item.get("id") and (
                not isinstance(item.get("evidence_ids"), list) or not item.get("evidence_ids")
            )
        }
        conflict_items = report.get("conflicts") if isinstance(report.get("conflicts"), list) else []
        expected_conflicts = {
            str(item.get("id") or f"legacy-conflict-{index + 1}")
            for index, item in enumerate(conflict_items)
            if isinstance(item, dict)
        }
        missing = {
            "测试点": expected_test_points - reviewed["test_points"],
            "未覆盖证据": expected_evidence - reviewed["evidence"],
            "未引用分析项": expected_analysis_items - reviewed["analysis_items"],
            "合并冲突": expected_conflicts - reviewed["conflicts"],
        }
        missing = {label: values for label, values in missing.items() if values}
        if missing:
            summary = "；".join(f"{label}还需核对{len(values)}项" for label, values in missing.items())
            raise RequirementAnalysisConfirmationError(f"审核未完成：{summary}。请在需求分析页逐项勾选后再确认。")
        if expected_conflicts:
            conflict_review = report.get("conflict_review") if isinstance(report.get("conflict_review"), dict) else {}
            report["conflict_review"] = {
                **conflict_review,
                "required": True,
                "status": "resolved",
                "pending_conflict_ids": [],
                "resolved_conflict_ids": sorted(reviewed["conflicts"] & expected_conflicts),
            }
        report.update({
            "quality_status": RequirementAnalysis.QualityStatus.COMPLETE,
            "needs_confirmation": False,
            "manual_confirmation": {
                "confirmed": True,
                "confirmed_by": str(getattr(user, "username", "")),
                "reviewed_test_point_ids": sorted(reviewed["test_points"]),
                "reviewed_evidence_ids": sorted(reviewed["evidence"]),
                "reviewed_analysis_item_ids": sorted(reviewed["analysis_items"]),
                "reviewed_conflict_ids": sorted(reviewed["conflicts"]),
            },
        })
        report.update(analysis_review_state(RequirementAnalysis.QualityStatus.COMPLETE, report))
        analysis.coverage_report = report
        analysis.quality_status = RequirementAnalysis.QualityStatus.COMPLETE
        analysis.save(update_fields=("quality_status", "coverage_report"))
        return locked_document

    @transaction.atomic
    def mark_test_points_reviewed(
        self,
        document: RequirementDocument,
        user: Any,
        *,
        reviewed_test_point_ids: list[str] | None = None,
    ) -> RequirementDocument:
        """Persist selected reviewed test points without finalizing the analysis."""
        del user
        locked_document = RequirementDocument.objects.select_for_update().get(pk=document.pk)
        analysis = locked_document.analyses.select_for_update().order_by("-created_at").first()
        if analysis is None:
            raise RequirementAnalysisConfirmationError("需求文档尚未完成需求分析。")
        if analysis.quality_status in {
            RequirementAnalysis.QualityStatus.PARTIAL,
            RequirementAnalysis.QualityStatus.FAILED,
        }:
            raise RequirementAnalysisConfirmationError("当前分析仍未完成，不能审核测试点；请先恢复需求分析。")
        expected = {
            str(item.get("id")) for item in (analysis.test_points or [])
            if isinstance(item, dict) and item.get("id")
        }
        reviewed = {str(value) for value in (reviewed_test_point_ids or [])}
        if reviewed - expected:
            raise RequirementAnalysisConfirmationError("审核列表包含当前分析不存在的测试点。")
        report = dict(analysis.coverage_report or {})
        previous = report.get("manual_confirmation") if isinstance(report.get("manual_confirmation"), dict) else {}
        report["manual_confirmation"] = {
            **previous,
            "confirmed": False,
            "reviewed_test_point_ids": sorted(reviewed),
            "reviewed_test_point_count": len(reviewed),
        }
        report.update(analysis_review_state(analysis.quality_status, report))
        analysis.coverage_report = report
        analysis.save(update_fields=("coverage_report",))
        return locked_document


__all__ = ["RequirementAnalysisConfirmationError", "RequirementAnalysisRecordService"]
