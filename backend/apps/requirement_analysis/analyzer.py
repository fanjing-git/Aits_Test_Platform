"""Deterministic requirement decomposition for the analysis pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument


class RequirementAnalysisError(ValueError):
    """Raised when a requirement cannot produce a useful structured analysis."""


@dataclass(frozen=True)
class DeepAnalysis:
    """Structured output consumed by persistence and later case generation tasks."""

    modules: list[dict[str, Any]]
    functions: list[dict[str, Any]]
    linkages: list[dict[str, Any]]
    test_points: list[dict[str, Any]]
    coverage_report: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible analysis payload."""
        return {
            "modules": self.modules,
            "functions": self.functions,
            "linkages": self.linkages,
            "test_points": self.test_points,
            "coverage_report": self.coverage_report,
        }


_HEADING = re.compile(r"^(?:#{1,6}\s*|(?:\d+[.)]|[一二三四五六七八九十]+[、.])\s*)(.+?)\s*$")
_ACTOR_TERMS = ("用户", "管理员", "操作员", "客服", "系统", "客户端", "服务端", "user", "admin")
_DATA_TERMS = re.compile(r"(?i)([a-z][a-z0-9_-]*(?:id|token|code|name)|用户信息|订单|支付|地址|凭证|文件|配置|状态)")


def _sentences(text: str) -> list[str]:
    """Split normalized requirement text into bounded meaningful sentences."""
    return [item.strip(" -\t") for item in re.split(r"[。！？!?；;\n]+", text) if item.strip(" -\t")]


def _module_sections(text: str) -> list[tuple[str, list[str]]]:
    """Group sentences beneath Markdown or numbered headings."""
    sections: list[tuple[str, list[str]]] = []
    current = "需求概览"
    buffer: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        heading = _HEADING.match(line)
        if heading:
            if buffer:
                sections.append((current, buffer)); buffer = []
            current = heading.group(1).strip(" :：")[:100] or "需求概览"
            continue
        buffer.extend(_sentences(line))
    if buffer:
        sections.append((current, buffer))
    if not sections:
        raise RequirementAnalysisError("需求文本不能为空。")
    return sections


def _relationship(source: str, target: str) -> str:
    """Infer a small, explainable relation label from requirement wording."""
    value = f"{source} {target}"
    if any(word in value.casefold() for word in ("调用", "依赖", "before", "after", "先", "后")):
        return "dependency"
    if any(word in value.casefold() for word in ("展示", "显示", "页面", "view")):
        return "display"
    if any(word in value.casefold() for word in ("同步", "更新", "共享", "sync")):
        return "data_link"
    return "sequence"


def deep_analyze(text: str, *, title: str = "需求文档") -> DeepAnalysis:
    """Decompose requirement text into modules, functions, flows and test points.

    The implementation is intentionally deterministic and explainable. It does not
    execute document content or call an external model; a later LLM stage can use
    this stable structure as its bounded input.
    """
    normalized = "\n".join(line.strip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
    if not normalized:
        raise RequirementAnalysisError("需求文本不能为空。")
    sections = _module_sections(normalized)
    modules: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    actors = sorted({term for term in _ACTOR_TERMS if term.casefold() in normalized.casefold()})
    for module_index, (module_name, sentences) in enumerate(sections, start=1):
        module_id = f"module-{module_index}"
        modules.append({"id": module_id, "name": module_name, "summary": sentences[0][:160], "actors": actors})
        for function_index, sentence in enumerate(sentences, start=1):
            functions.append({
                "id": f"{module_id}-function-{function_index}",
                "module_id": module_id,
                "name": sentence[:100],
                "description": sentence,
                "actors": [actor for actor in actors if actor.casefold() in sentence.casefold()],
                "acceptance_criteria": [f"{sentence[:120]}可完成并返回可验证结果"],
            })
    linkages: list[dict[str, Any]] = []
    for previous, current in zip(functions, functions[1:]):
        linkages.append({"from": previous["id"], "to": current["id"], "relationship": _relationship(previous["description"], current["description"]), "evidence": f"{previous['name']} → {current['name']}"})
    data_flows: list[dict[str, Any]] = []
    for index, function in enumerate(functions):
        data_items = sorted(set(_DATA_TERMS.findall(function["description"])))
        if data_items and index + 1 < len(functions):
            data_flows.append({"data": data_items, "from": function["id"], "to": functions[index + 1]["id"], "direction": "forward"})
    test_points = [{"id": f"test-point-{index}", "function_id": function["id"], "type": kind, "description": f"验证{function['name']}的{label}"} for index, (function, kind, label) in enumerate(((item, "positive", "正常流程") for item in functions), start=1)]
    for function in functions:
        test_points.extend([
            {"id": f"test-point-{len(test_points) + 1}", "function_id": function["id"], "type": "negative", "description": f"验证{function['name']}的异常输入和权限拒绝"},
            {"id": f"test-point-{len(test_points) + 2}", "function_id": function["id"], "type": "boundary", "description": f"验证{function['name']}的边界值和重复提交"},
        ])
    coverage = {
        "title": title,
        "module_count": len(modules),
        "function_count": len(functions),
        "linkage_count": len(linkages),
        "data_flow_count": len(data_flows),
        "test_point_count": len(test_points),
        "actors": actors,
        "data_flows": data_flows,
        "completeness": round(min(1.0, len(test_points) / max(1, len(functions) * 3)), 4),
    }
    return DeepAnalysis(modules, functions, linkages, test_points, coverage)


@transaction.atomic
def analyze_requirement_document(document: RequirementDocument) -> RequirementAnalysis:
    """Analyze a parsed document and persist a new immutable result."""
    if not document.content_text.strip():
        raise RequirementAnalysisError("需求文档尚未解析出正文。")
    document.status = RequirementDocument.Status.ANALYZING
    document.save(update_fields=("status",))
    try:
        result = deep_analyze(document.content_text, title=document.title)
        analysis = RequirementAnalysis.objects.create(document=document, **result.as_dict())
        document.status = RequirementDocument.Status.ANALYZED
        document.save(update_fields=("status",))
        return analysis
    except RequirementAnalysisError:
        document.status = RequirementDocument.Status.FAILED
        document.save(update_fields=("status",))
        raise


__all__ = ["DeepAnalysis", "RequirementAnalysisError", "analyze_requirement_document", "deep_analyze"]
