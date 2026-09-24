"""Transactional services for requirement-analysis record lifecycle actions."""

import hashlib
import json
from typing import Any

from django.db import transaction
from django.utils import timezone

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

    @transaction.atomic
    def review_latest_analysis(self, document: RequirementDocument) -> RequirementAnalysis:
        """Run the persisted requirement-review Skill against the latest analysis.

        This review is deliberately separate from test-point approval. It validates
        that the analysis version has enough traceability for decomposition, then
        freezes the reviewed source fingerprint used by the next stage.
        """
        locked_document = RequirementDocument.objects.select_for_update().get(pk=document.pk)
        analysis = locked_document.analyses.select_for_update().order_by("-created_at").first()
        if analysis is None:
            raise RequirementAnalysisConfirmationError("需求文档尚未完成需求分析，不能进行需求评审。")
        if analysis.quality_status in {
            RequirementAnalysis.QualityStatus.PARTIAL,
            RequirementAnalysis.QualityStatus.FAILED,
        }:
            raise RequirementAnalysisConfirmationError("当前分析不是可评审的完整版本，请先恢复需求分析。")
        mapping_gaps = analysis_mapping_gaps({
            "modules": analysis.modules,
            "functions": analysis.functions,
            "linkages": analysis.linkages,
            "test_points": analysis.test_points,
        })
        issues: list[dict[str, Any]] = []
        for category, values in mapping_gaps.items():
            for value in values:
                issues.append({"code": category, "item_id": str(value), "message": "结构映射不完整。"})
        functions = [item for item in (analysis.functions or []) if isinstance(item, dict)]
        acceptance_count = sum(bool(item.get("acceptance_criteria")) for item in functions)
        flow_count = len((analysis.coverage_report or {}).get("data_flows") or [])
        if not functions:
            issues.append({"code": "empty_functions", "item_id": "", "message": "没有可追溯的功能点。"})
        if acceptance_count != len(functions):
            issues.append({"code": "acceptance_criteria", "item_id": "", "message": "存在功能点缺少验收条件。"})
        report = {
            "schema_version": "requirement-review-v1",
            "source_analysis_id": str(analysis.pk),
            "source_fingerprint": analysis.analysis_fingerprint,
            "status": "failed" if issues else "passed",
            "reviewed_counts": {
                "modules": len(analysis.modules or []),
                "functions": len(functions),
                "linkages": len(analysis.linkages or []),
                "data_flows": flow_count,
                "acceptance_conditions": acceptance_count,
            },
            "issues": issues,
            "reviewed_at": timezone.now().isoformat(),
        }
        analysis.review_report = report
        analysis.review_status = RequirementAnalysis.StageStatus.PASSED if not issues else RequirementAnalysis.StageStatus.FAILED
        analysis.decomposition_status = RequirementAnalysis.StageStatus.PENDING
        analysis.decomposition = {}
        analysis.decomposition_fingerprint = ""
        analysis.save(update_fields=("review_status", "review_report", "decomposition_status", "decomposition", "decomposition_fingerprint"))
        return analysis

    @transaction.atomic
    def decompose_reviewed_analysis(self, document: RequirementDocument) -> RequirementAnalysis:
        """Create a traceable decomposition only from a passed review snapshot."""
        locked_document = RequirementDocument.objects.select_for_update().get(pk=document.pk)
        analysis = locked_document.analyses.select_for_update().order_by("-created_at").first()
        if analysis is None or analysis.review_status != RequirementAnalysis.StageStatus.PASSED:
            raise RequirementAnalysisConfirmationError("需求拆解只能消费已通过需求评审的版本。")
        review_report = dict(analysis.review_report or {})
        if review_report.get("source_analysis_id") != str(analysis.pk) or review_report.get("source_fingerprint") != analysis.analysis_fingerprint:
            raise RequirementAnalysisConfirmationError("需求评审版本已失效，请重新执行需求评审。")
        modules = [dict(item) for item in (analysis.modules or []) if isinstance(item, dict)]
        functions = [dict(item) for item in (analysis.functions or []) if isinstance(item, dict)]
        module_ids = {str(item.get("id")) for item in modules if item.get("id")}
        traceable_functions = [item for item in functions if str(item.get("module_id")) in module_ids]
        flows = []
        for index, function in enumerate(traceable_functions):
            flows.append({
                "id": f"flow-{index + 1}",
                "steps": [function.get("id")],
                "module_id": function.get("module_id"),
                "name": function.get("name") or f"业务流程 {index + 1}",
                "source_function_ids": [function.get("id")],
            })
        flows.extend({
            "id": f"flow-link-{index + 1}",
            "steps": [item.get("from"), item.get("to")],
            "name": item.get("evidence") or f"功能联动 {index + 1}",
            "relationship": item.get("relationship", "related"),
            "source_linkage": item.get("id") or f"linkage-{index + 1}",
        } for index, item in enumerate(analysis.linkages or []) if isinstance(item, dict))
        data_names: set[str] = set()
        data_objects = []
        for item in (analysis.coverage_report or {}).get("data_flows", []) or []:
            if not isinstance(item, dict):
                continue
            for name in item.get("data", []) or []:
                name = str(name).strip()
                if name and name not in data_names:
                    data_names.add(name)
                    data_objects.append({"id": f"data-{len(data_objects) + 1}", "name": name, "source_flow": item.get("from"), "target_flow": item.get("to")})
        acceptance_conditions = [
            {"id": f"acceptance-{index + 1}", "function_id": item.get("id"), "conditions": list(item.get("acceptance_criteria") or []), "evidence_ids": list(item.get("evidence_ids") or [])}
            for index, item in enumerate(traceable_functions)
        ]
        result = {
            "schema_version": "requirement-decomposition-v1",
            "source_analysis_id": str(analysis.pk),
            "source_fingerprint": analysis.analysis_fingerprint,
            "review_run_id": str(analysis.review_run_id or ""),
            "modules": modules,
            "functions": traceable_functions,
            "business_flows": flows,
            "data_objects": data_objects,
            "acceptance_conditions": acceptance_conditions,
        }
        fingerprint = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        result["decomposition_fingerprint"] = fingerprint
        analysis.decomposition = result
        analysis.decomposition_fingerprint = fingerprint
        analysis.decomposition_status = RequirementAnalysis.StageStatus.COMPLETED
        analysis.save(update_fields=("decomposition", "decomposition_fingerprint", "decomposition_status"))
        return analysis


__all__ = ["RequirementAnalysisConfirmationError", "RequirementAnalysisRecordService"]
