"""Explainable cross-module linkage detection for requirement analysis."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from django.db import transaction

from apps.requirement_analysis.models import RequirementAnalysis


class LinkageAnalysisError(ValueError):
    """Raised when a linkage input is malformed or cannot be analyzed."""


@dataclass(frozen=True)
class LinkageResult:
    """Cross-module scenarios and their directly testable checkpoints."""

    scenarios: list[dict[str, Any]]
    test_points: list[dict[str, Any]]
    summary: dict[str, int]


_STOP_WORDS = {"用户", "系统", "功能", "支持", "可以", "需要", "进行", "并", "后", "时", "the", "and", "with"}
_DATA_TERMS = re.compile(r"(?i)([a-z][a-z0-9_-]*(?:id|token|code|name|status)|用户信息|订单|支付|地址|凭证|文件|配置|状态|权限)")
_WORD_TERMS = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}")


def _terms(value: str) -> set[str]:
    """Extract comparable business terms while ignoring generic wording."""
    return {item.casefold() for item in _WORD_TERMS.findall(value or "") if item.casefold() not in _STOP_WORDS}


def _relation(source: Mapping[str, Any], target: Mapping[str, Any], shared: set[str]) -> str:
    """Classify a linkage using explicit requirement vocabulary."""
    text = f"{source.get('description', '')} {target.get('description', '')}".casefold()
    if any(word in text for word in ("展示", "显示", "页面", "view", "render")):
        return "display"
    if any(word in text for word in ("状态", "启用", "停用", "取消", "完成", "state", "status")):
        return "state_link"
    if any(word in text for word in ("调用", "依赖", "前置", "登录后", "调用", "depend")):
        return "dependency"
    if shared & {item.casefold() for item in _DATA_TERMS.findall(text)}:
        return "data_link"
    return "sequence"


def identify_linkages(analysis: Mapping[str, Any]) -> LinkageResult:
    """Identify explicit cross-module relations from a T043 analysis payload."""
    functions = analysis.get("functions") if isinstance(analysis, Mapping) else None
    modules = analysis.get("modules") if isinstance(analysis, Mapping) else None
    if not isinstance(functions, list) or not isinstance(modules, list):
        raise LinkageAnalysisError("分析结果必须包含 modules 和 functions 数组。")
    module_ids = {item.get("id") for item in modules if isinstance(item, Mapping)}
    candidates = [item for item in functions if isinstance(item, Mapping) and item.get("id") and item.get("module_id") in module_ids]
    scenarios: list[dict[str, Any]] = []
    counts: dict[str, int] = {"dependency": 0, "display": 0, "state_link": 0, "data_link": 0, "sequence": 0}
    for index, source in enumerate(candidates):
        source_terms = _terms(f"{source.get('name', '')} {source.get('description', '')}")
        for target in candidates[index + 1:]:
            if source.get("module_id") == target.get("module_id"):
                continue
            target_terms = _terms(f"{target.get('name', '')} {target.get('description', '')}")
            shared = source_terms & target_terms
            data_shared = {item.casefold() for item in _DATA_TERMS.findall(f"{source.get('description', '')} {target.get('description', '')}")}
            if not shared and not data_shared:
                continue
            relation = _relation(source, target, shared | data_shared)
            counts[relation] += 1
            scenarios.append({
                "id": f"linkage-{len(scenarios) + 1}",
                "from": source["id"],
                "to": target["id"],
                "from_module": source["module_id"],
                "to_module": target["module_id"],
                "relationship": relation,
                "shared_terms": sorted(shared | data_shared),
                "evidence": f"{source.get('name', source['id'])} → {target.get('name', target['id'])}",
            })
    test_points = [
        {"id": f"linkage-test-{index}", "scenario_id": item["id"], "type": "linkage", "description": f"验证{item['evidence']}的{item['relationship']}联动"}
        for index, item in enumerate(scenarios, start=1)
    ]
    return LinkageResult(scenarios, test_points, {key: value for key, value in counts.items() if value})


@transaction.atomic
def identify_document_linkages(analysis: RequirementAnalysis) -> RequirementAnalysis:
    """Persist cross-module linkage scenarios and append linkage test points."""
    result = identify_linkages({"modules": analysis.modules, "functions": analysis.functions})
    existing = analysis.test_points if isinstance(analysis.test_points, list) else []
    analysis.linkages = result.scenarios
    analysis.test_points = existing + result.test_points
    analysis.coverage_report = {**(analysis.coverage_report if isinstance(analysis.coverage_report, dict) else {}), "cross_module_linkage_count": len(result.scenarios), "linkage_relationships": result.summary}
    analysis.save(update_fields=("linkages", "test_points", "coverage_report"))
    return analysis


__all__ = ["LinkageAnalysisError", "LinkageResult", "identify_document_linkages", "identify_linkages"]
