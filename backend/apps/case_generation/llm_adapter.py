"""Optional structured model adapters for test case generation and review."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from apps.configs.models import ModelConfig, PromptConfig
from apps.case_generation.models import CaseGenerationRecord
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter


class CaseGenerationModelAdapter:
    """Reuse the configured structured runtime with case-specific validation."""

    def __init__(self, **kwargs: Any) -> None:
        self.adapter = RequirementModelAdapter(**kwargs)

    def generate(self, *, functions: Sequence[Mapping[str, Any]], linkages: Sequence[Mapping[str, Any]], evidence: Sequence[Mapping[str, Any]], project_name: str | None = None) -> dict[str, Any]:
        """Generate validated cases from bounded function and linkage evidence."""
        payload = self.adapter.run(text=str({"functions": list(functions), "linkages": list(linkages)}), evidence=evidence, project_name=project_name, task_type="case_gen", scene_type=PromptConfig.SceneType.CASE_GEN)
        cases = payload.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ModelAnalysisError("模型输出缺少可执行用例。")
        function_ids = {str(item.get("id")) for item in functions}
        validated: list[dict[str, Any]] = []
        for item in cases:
            if not isinstance(item, Mapping):
                raise ModelAnalysisError("模型用例格式无效。")
            source_id = str(item.get("source_function_id", ""))
            if source_id not in function_ids or item.get("type") not in {"positive", "negative", "boundary", "linkage"} or not item.get("title") or not item.get("steps") or not item.get("expected_result"):
                raise ModelAnalysisError("模型用例缺少有效来源或必填字段。")
            validated.append(dict(item))
        return {"cases": validated, "coverage_report": dict(payload.get("coverage_report") or {}), "round_trace": payload.get("round_trace") if isinstance(payload.get("round_trace"), list) else []}


def _validate_review_payload(payload: Mapping[str, Any], case_ids: set[str], evidence_ids: set[str]) -> dict[str, Any]:
    """Validate model review output against the immutable generation scope."""
    issues = payload.get("issues")
    corrections = payload.get("corrections", [])
    if not isinstance(issues, list) or not isinstance(corrections, list) or not isinstance(payload.get("approved"), bool):
        raise ModelAnalysisError("模型评审输出缺少结构化字段。")
    normalized_issues: list[dict[str, Any]] = []
    for index, raw in enumerate(issues, start=1):
        if not isinstance(raw, Mapping):
            raise ModelAnalysisError("模型评审问题格式无效。")
        case_id = str(raw.get("case_id", "")).strip()
        if case_id and case_id not in case_ids:
            raise ModelAnalysisError("模型评审引用了不存在的用例。")
        severity = str(raw.get("severity", "medium")).strip().lower()
        if severity not in {"high", "medium", "low"}:
            raise ModelAnalysisError("模型评审严重级别无效。")
        description = str(raw.get("description", "")).strip()
        suggestion = str(raw.get("suggestion", "")).strip()
        if not description or not suggestion:
            raise ModelAnalysisError("模型评审问题缺少描述或修正建议。")
        cited = raw.get("evidence_ids", [])
        if not isinstance(cited, list) or not set(map(str, cited)).issubset(evidence_ids):
            raise ModelAnalysisError("模型评审引用了不存在的证据。")
        normalized_issues.append({
            "id": str(raw.get("id") or f"model-issue-{index}"),
            "code": str(raw.get("code") or "model_review_issue"),
            "case_id": case_id,
            "severity": severity,
            "dimension": str(raw.get("dimension") or "model_review"),
            "description": description,
            "suggestion": suggestion,
            "evidence_ids": [str(item) for item in cited],
            "source": "model",
        })
    normalized_corrections: list[dict[str, Any]] = []
    for raw in corrections:
        if not isinstance(raw, Mapping) or str(raw.get("case_id", "")) not in case_ids:
            raise ModelAnalysisError("模型修正建议引用了不存在的用例。")
        field = str(raw.get("field", "")).strip()
        if field not in {"title", "steps", "expected_result", "priority", "type"}:
            raise ModelAnalysisError("模型修正字段不在允许范围内。")
        normalized_corrections.append({"case_id": str(raw["case_id"]), "field": field, "value": raw.get("value")})
    return {
        "issues": normalized_issues,
        "corrections": normalized_corrections,
        "approved": payload["approved"],
        "summary": str(payload.get("summary") or "").strip(),
    }


class CaseReviewModelAdapter:
    """Route five-round case review through the configured chat model."""

    def __init__(self, **kwargs: Any) -> None:
        self.adapter = RequirementModelAdapter(**kwargs)

    def review(self, *, record: CaseGenerationRecord, project_name: str | None = None) -> dict[str, Any]:
        """Review only the cases and requirement belonging to the supplied record."""
        cases = [item for item in record.cases if isinstance(item, Mapping)]
        if not cases:
            raise ModelAnalysisError("没有可供模型评审的用例。")
        case_ids = {str(item.get("id")) for item in cases if item.get("id")}
        evidence = record.document.parse_evidence if isinstance(record.document.parse_evidence, list) else []
        evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
        bounded = {"requirement": record.document.content_text, "cases": cases}
        instruction = (
            "Output ONLY valid JSON, with no Markdown. Required keys: issues, corrections, approved, summary. "
            "issues is an array; each issue has id, code, case_id (empty for requirement-level issues), severity "
            "(high/medium/low), dimension, description, suggestion, and evidence_ids. corrections is an array; "
            "its field must be one of title, steps, expected_result, priority, or type. Use only supplied case IDs "
            "and evidence IDs; never invent cases. Perform five review rounds: initial, requirement comparison, "
            "deviation correction, re-review, and final report. approved is true only when no high or medium issue exists."
        )
        return self.adapter.run(
            text=json.dumps(bounded, ensure_ascii=False),
            evidence=evidence,
            project_name=project_name,
            task_type="case_review",
            scene_type=PromptConfig.SceneType.CASE_REVIEW,
            instant_prompt=instruction,
            prompt_override=instruction,
            validator=lambda payload: _validate_review_payload(payload, case_ids, evidence_ids),
        )


__all__ = ["CaseGenerationModelAdapter", "CaseReviewModelAdapter"]
