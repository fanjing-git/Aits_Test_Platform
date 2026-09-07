"""Optional structured model adapters for test case generation and review."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from apps.configs.models import ModelConfig, PromptConfig
from apps.case_generation.models import CaseGenerationRecord
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter


class CaseGenerationModelAdapter:
    """Run five incremental model passes over one analyzed requirement."""

    ROUND_INSTRUCTIONS = {
        1: "只生成需求主流程和验收标准对应的新增用例，覆盖每个核心功能点。",
        2: "基于已有用例补充异常、权限、输入校验、依赖失败和安全风险场景，只返回新增用例。",
        3: "基于已有用例补充边界值、状态转换、并发、重复提交、恢复和数据一致性场景，只返回新增用例。",
        4: "基于模块关系、功能点和联合场景补充跨模块、数据流、接口契约和业务链路遗漏，只返回新增用例。",
        5: "执行最终覆盖审查，针对仍未覆盖的测试点、风险和回归影响补充最小必要新增用例，只返回新增用例。",
    }

    def __init__(self, **kwargs: Any) -> None:
        self.adapter = RequirementModelAdapter(**kwargs)

    @staticmethod
    def _validate_cases(
        payload: Mapping[str, Any],
        function_ids: set[str],
        linkage_ids: set[str],
    ) -> dict[str, Any]:
        """Validate one round while retaining every distinct scenario."""
        cases = payload.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ModelAnalysisError("模型输出缺少本轮新增用例。")
        validated: list[dict[str, Any]] = []
        for item in cases:
            if not isinstance(item, Mapping):
                raise ModelAnalysisError("模型用例格式无效。")
            source_id = str(item.get("source_function_id", ""))
            case_type = str(item.get("type", "")).strip()
            linkage_id = str(item.get("linkage_id", "")).strip()
            if source_id not in function_ids or case_type not in {"positive", "negative", "boundary", "linkage"}:
                raise ModelAnalysisError("模型用例缺少有效来源或类型。")
            if case_type == "linkage" and linkage_id and linkage_id not in linkage_ids:
                raise ModelAnalysisError("模型用例引用了不存在的联合场景。")
            if not item.get("title") or not isinstance(item.get("steps"), list) or not item.get("steps") or not item.get("expected_result"):
                raise ModelAnalysisError("模型用例缺少标题、步骤或预期结果。")
            normalized = dict(item)
            normalized["source_function_id"] = source_id
            normalized["type"] = case_type
            normalized["steps"] = [str(step).strip() for step in item["steps"] if str(step).strip()]
            normalized["expected_result"] = str(item["expected_result"]).strip()
            normalized["title"] = str(item["title"]).strip()
            normalized["linkage_id"] = linkage_id or None
            validated.append(normalized)
        return {
            "cases": validated,
            "coverage_report": dict(payload.get("coverage_report") or {}),
            "round_analysis": dict(payload.get("round_analysis") or {}) if isinstance(payload.get("round_analysis"), Mapping) else {},
        }

    def generate_round(
        self,
        *,
        round_number: int,
        document_text: str,
        modules: Sequence[Mapping[str, Any]],
        functions: Sequence[Mapping[str, Any]],
        test_points: Sequence[Mapping[str, Any]],
        linkages: Sequence[Mapping[str, Any]],
        existing_cases: Sequence[Mapping[str, Any]],
        evidence: Sequence[Mapping[str, Any]],
        project_name: str | None = None,
        preferred_model_name: str | None = None,
    ) -> dict[str, Any]:
        """Call the configured model once for one incremental coverage pass."""
        if round_number not in self.ROUND_INSTRUCTIONS:
            raise ModelAnalysisError("用例生成轮次必须在 1 到 5 之间。")
        scope = {
            "round": round_number,
            "document": document_text,
            "modules": list(modules),
            "functions": list(functions),
            "test_points": list(test_points),
            "linkages": list(linkages),
            "existing_cases": list(existing_cases),
        }
        instruction = (
            "你正在对同一份需求执行第 %d 轮递进式测试用例分析。%s "
            "需求分析结果和已有用例是输入上下文；不要重复已有用例，不要把五轮当成五次独立生成。 "
            "只输出 JSON：{\"round_analysis\":{...},\"cases\":[...],\"coverage_report\":{...}}。round_analysis 必须说明本轮复核的需求风险、已覆盖测试点和仍待覆盖的缺口。每个新增用例必须包含 "
            "source_function_id、type、title、steps、expected_result、priority、automatable；"
            "source_function_id 必须来自 functions，linkage_id 必须来自 linkages。"
        ) % (round_number, self.ROUND_INSTRUCTIONS[round_number])
        function_ids = {str(item.get("id")) for item in functions}
        linkage_ids = {str(item.get("id")) for item in linkages}
        return self.adapter.run(
            text=json.dumps(scope, ensure_ascii=False),
            evidence=evidence,
            project_name=project_name,
            task_type="case_gen",
            scene_type=PromptConfig.SceneType.CASE_GEN,
            instant_prompt=instruction,
            prompt_override=instruction,
            validator=lambda payload: self._validate_cases(payload, function_ids, linkage_ids),
            preferred_model_name=preferred_model_name,
        )

    def generate(self, *, functions: Sequence[Mapping[str, Any]], linkages: Sequence[Mapping[str, Any]], evidence: Sequence[Mapping[str, Any]], project_name: str | None = None) -> dict[str, Any]:
        """Keep the original one-pass contract for integrations and tests."""
        return self.generate_round(
            round_number=1,
            document_text="",
            modules=[],
            functions=functions,
            test_points=[],
            linkages=linkages,
            existing_cases=[],
            evidence=evidence,
            project_name=project_name,
        )


REVIEW_SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}


def _localize_review_text(value: str, *, suggestion: bool = False) -> str:
    """Return a concise Chinese label for common model review phrases."""
    text = value.strip()
    lowered = text.casefold()
    mappings = (
        (("garbled", "not understandable", "unreadable"), "需求文本存在乱码或不可理解内容，请补充清晰、完整的需求说明。"),
        (("steps are generic", "lack specific actions", "lack specific input data"), "测试步骤过于笼统，缺少具体操作和测试数据。"),
        (("expected result is vague", "expected results are vague", "does not specify exact expected outcomes"), "预期结果描述不明确，无法直接验证实际结果。"),
        (("lack specificity", "insufficient for automated testing"), "用例描述不够具体，暂不满足可执行和自动化验证要求。"),
    )
    for phrases, localized in mappings:
        if any(phrase in lowered for phrase in phrases):
            return localized
    if any(word in lowered for word in ("provide", "detail", "specify")):
        return "请根据需求补充可执行的操作、输入和预期结果。" if suggestion else "模型发现当前评审记录仍缺少可验证细节。"
    if text and all(ord(char) < 128 for char in text):
        return "请结合需求证据核对模型指出的问题。" if not suggestion else "请补充可执行的操作、输入和预期结果。"
    return text


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
        localized_description = _localize_review_text(description)
        localized_suggestion = _localize_review_text(suggestion, suggestion=True)
        normalized_issues.append({
            "id": str(raw.get("id") or f"model-issue-{index}"),
            "code": str(raw.get("code") or "model_review_issue"),
            "case_id": case_id,
            "severity": severity,
            "severity_label": REVIEW_SEVERITY_LABELS[severity],
            "dimension": str(raw.get("dimension") or "model_review"),
            "description": localized_description,
            "suggestion": localized_suggestion,
            "model_description": description,
            "model_suggestion": suggestion,
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

    def review(
        self,
        *,
        record: CaseGenerationRecord,
        project_name: str | None = None,
        round_number: int = 1,
        existing_issues: Sequence[Mapping[str, Any]] = (),
        existing_corrections: Sequence[Mapping[str, Any]] = (),
        preferred_model_name: str | None = None,
    ) -> dict[str, Any]:
        """Review only the cases and requirement belonging to the supplied record."""
        cases = [item for item in record.cases if isinstance(item, Mapping)]
        if not cases:
            raise ModelAnalysisError("没有可供模型评审的用例。")
        case_ids = {str(item.get("id")) for item in cases if item.get("id")}
        evidence = record.document.parse_evidence if isinstance(record.document.parse_evidence, list) else []
        evidence_ids = {str(item.get("id")) for item in evidence if item.get("id")}
        bounded = {
            "round": round_number,
            "requirement": record.document.content_text,
            "cases": cases,
            "existing_issues": list(existing_issues),
            "existing_corrections": list(existing_corrections),
        }
        instruction = (
            "Output ONLY valid JSON, with no Markdown. Required keys: issues, corrections, approved, summary. "
            "issues is an array; each issue has id, code, case_id (empty for requirement-level issues), severity "
            "(high/medium/low), dimension, description, suggestion, and evidence_ids. corrections is an array; "
            "its field must be one of title, steps, expected_result, priority, or type. Use only supplied case IDs "
            "and evidence IDs; never invent cases. This is review round %d of five; inspect existing findings and return only new findings or corrections. "
            "approved is true only when no high or medium issue exists."
        ) % round_number
        return self.adapter.run(
            text=json.dumps(bounded, ensure_ascii=False),
            evidence=evidence,
            project_name=project_name,
            task_type="case_review",
            scene_type=PromptConfig.SceneType.CASE_REVIEW,
            instant_prompt=instruction,
            prompt_override=instruction,
            validator=lambda payload: _validate_review_payload(payload, case_ids, evidence_ids),
            preferred_model_name=preferred_model_name,
        )


__all__ = ["CaseGenerationModelAdapter", "CaseReviewModelAdapter"]
