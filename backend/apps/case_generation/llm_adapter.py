"""Optional structured model adapter for test case generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from apps.configs.models import ModelConfig, PromptConfig
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


__all__ = ["CaseGenerationModelAdapter"]
