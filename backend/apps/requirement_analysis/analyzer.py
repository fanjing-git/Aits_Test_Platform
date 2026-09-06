"""Deterministic requirement decomposition for the analysis pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.configs.models import ModelConfig
from apps.requirement_analysis.llm_adapter import ModelAnalysisError, RequirementModelAdapter
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


def _function_test_points(function: dict[str, Any], start: int, *, evidence_ids: list[str] | None = None, needs_confirmation: bool = False) -> list[dict[str, Any]]:
    """Build a broad but explainable baseline around one function."""
    name = function["name"]
    function_id = function["id"]
    cases = [
        ("positive", "正常流程", "验证功能按需求完成并给出可确认结果"),
        ("negative", "输入校验", "验证缺少必填项、格式错误或非法值时给出明确提示"),
        ("negative", "权限拒绝", "验证未授权角色无法执行该功能且不泄露受限数据"),
        ("negative", "依赖失败", "验证依赖服务超时或返回错误时能安全失败并保留可重试状态"),
        ("boundary", "边界值", "验证最小值、最大值、空集合和超长输入均有明确处理"),
        ("boundary", "重复提交", "验证连续点击、刷新或重复请求不会造成重复数据或重复扣减"),
        ("boundary", "状态恢复", "验证中断、网络恢复和重新进入页面后状态与结果保持一致"),
    ]
    return [
        {"id": f"test-point-{start + index}", "function_id": function_id, "type": kind, "scenario": scenario, "description": f"{description}：{name}", "evidence_ids": evidence_ids or [], "needs_confirmation": needs_confirmation}
        for index, (kind, scenario, description) in enumerate(cases)
    ]


def deep_analyze(text: str, *, title: str = "需求文档", source_type: str = "manual", evidence: list[dict[str, Any]] | None = None, source_confidence: float = 1.0, warnings: list[str] | None = None) -> DeepAnalysis:
    """Decompose requirement text into modules, functions, flows and test points.

    The implementation is intentionally deterministic and explainable. It does not
    execute document content or call an external model; a later LLM stage can use
    this stable structure as its bounded input.
    """
    normalized = "\n".join(line.strip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
    if not normalized:
        raise RequirementAnalysisError("需求文本不能为空。")
    warnings = list(warnings or [])
    needs_confirmation = source_confidence < 0.75 or bool(warnings)
    if source_type == RequirementDocument.SourceType.SCREENSHOT and needs_confirmation:
        normalized = ""
        sections = []
    else:
        sections = _module_sections(normalized)
    modules: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    actors = sorted({term for term in _ACTOR_TERMS if term.casefold() in normalized.casefold()})
    for module_index, (module_name, sentences) in enumerate(sections, start=1):
        module_id = f"module-{module_index}"
        modules.append({"id": module_id, "name": module_name, "summary": sentences[0][:160], "actors": actors, "evidence_ids": []})
        for function_index, sentence in enumerate(sentences, start=1):
            evidence_ids = []
            if evidence:
                evidence_ids = [str(item.get("id")) for item in evidence if sentence.casefold() in str(item.get("text", "")).casefold() or str(item.get("text", "")).casefold() in sentence.casefold()][:3]
            functions.append({
                "id": f"{module_id}-function-{function_index}",
                "module_id": module_id,
                "name": sentence[:100],
                "description": sentence,
                "actors": [actor for actor in actors if actor.casefold() in sentence.casefold()],
                "acceptance_criteria": [f"{sentence[:120]}可完成并返回可验证结果"],
                "evidence_ids": evidence_ids,
                "needs_confirmation": needs_confirmation,
            })
    linkages: list[dict[str, Any]] = []
    for previous, current in zip(functions, functions[1:]):
        linkages.append({"from": previous["id"], "to": current["id"], "relationship": _relationship(previous["description"], current["description"]), "evidence": f"{previous['name']} → {current['name']}"})
    data_flows: list[dict[str, Any]] = []
    for index, function in enumerate(functions):
        data_items = sorted(set(_DATA_TERMS.findall(function["description"])))
        if data_items and index + 1 < len(functions):
            data_flows.append({"data": data_items, "from": function["id"], "to": functions[index + 1]["id"], "direction": "forward"})
    test_points: list[dict[str, Any]] = []
    for function in functions:
        test_points.extend(_function_test_points(function, len(test_points) + 1, evidence_ids=function.get("evidence_ids", []), needs_confirmation=needs_confirmation))
    if source_type == RequirementDocument.SourceType.SCREENSHOT:
        visual_module_id = "module-visual-baseline"
        modules.append({"id": visual_module_id, "name": "截图界面行为基线", "summary": "基于截图可观察行为建立待人工确认的视觉测试基线", "actors": actors, "evidence_ids": [str(item.get("id")) for item in (evidence or [])]})
        visual_functions = (
            ("页面元素可见性", "验证关键文字、图标、按钮和交互区域在加载完成后可见且状态清晰"),
            ("界面导航与切换", "验证菜单、标签页和返回操作不会丢失当前上下文"),
            ("列表与网格状态", "验证列表或网格的加载、空数据、分页和溢出状态可理解"),
            ("操作反馈与错误提示", "验证点击、处理中、成功、失败和重试反馈及时且不会误导用户"),
        )
        for index, (name, description) in enumerate(visual_functions, start=1):
            function = {"id": f"{visual_module_id}-function-{index}", "module_id": visual_module_id, "name": name, "description": description, "actors": actors, "acceptance_criteria": [description], "evidence_ids": [str(item.get("id")) for item in (evidence or [])], "needs_confirmation": True}
            functions.append(function)
            test_points.extend(_function_test_points(function, len(test_points) + 1, evidence_ids=function["evidence_ids"], needs_confirmation=True))
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
        "source_confidence": round(max(0.0, min(1.0, source_confidence)), 4),
        "needs_confirmation": needs_confirmation,
        "analysis_method": "deterministic_evidence_baseline",
        "analysis_warnings": warnings,
        "evidence_count": len(evidence or []),
    }
    if source_type == RequirementDocument.SourceType.SCREENSHOT:
        coverage["visual_baseline"] = True
        coverage["visual_baseline_note"] = "截图 OCR 结果需人工确认；以上视觉基线不代表已识别出全部业务功能。"
    return DeepAnalysis(modules, functions, linkages, test_points, coverage)


@transaction.atomic
def analyze_requirement_document(document: RequirementDocument) -> RequirementAnalysis:
    """Analyze a parsed document and persist a new immutable result."""
    if not document.content_text.strip():
        raise RequirementAnalysisError("需求文档尚未解析出正文。")
    document.status = RequirementDocument.Status.ANALYZING
    document.save(update_fields=("status",))
    try:
        evidence = document.parse_evidence if isinstance(document.parse_evidence, list) else []
        warnings = document.parse_warnings if isinstance(document.parse_warnings, list) else []
        result: DeepAnalysis
        required_model_type = ModelConfig.ModelType.VISION if document.source_type == RequirementDocument.SourceType.SCREENSHOT else ModelConfig.ModelType.CHAT
        if ModelConfig.objects.filter(is_active=True, model_type=required_model_type).exists():
            try:
                model_payload = RequirementModelAdapter().analyze(text=document.content_text, evidence=evidence, project_name=document.project.name, task_type="screenshot" if document.source_type == RequirementDocument.SourceType.SCREENSHOT else "requirement_analysis", scene_type="screenshot_analysis" if document.source_type == RequirementDocument.SourceType.SCREENSHOT else "requirement_analysis")
                coverage = {**(model_payload.get("coverage_report") or {}), "title": document.title, "analysis_method": "model_verified", "source_confidence": document.parse_confidence, "evidence_count": len(evidence), "needs_confirmation": bool(warnings) or document.parse_confidence < 0.75}
                result = DeepAnalysis(model_payload["modules"], model_payload["functions"], model_payload["linkages"], model_payload["test_points"], coverage)
            except ModelAnalysisError as exc:
                warnings = [*warnings, str(exc)]
                result = deep_analyze(document.content_text, title=document.title, source_type=document.source_type, evidence=evidence, source_confidence=document.parse_confidence, warnings=warnings)
        else:
            result = deep_analyze(document.content_text, title=document.title, source_type=document.source_type, evidence=evidence, source_confidence=document.parse_confidence, warnings=warnings)
        analysis = RequirementAnalysis.objects.create(document=document, **result.as_dict())
        document.status = RequirementDocument.Status.ANALYZED
        document.save(update_fields=("status",))
        return analysis
    except RequirementAnalysisError:
        document.status = RequirementDocument.Status.FAILED
        document.save(update_fields=("status",))
        raise


__all__ = ["DeepAnalysis", "RequirementAnalysisError", "analyze_requirement_document", "deep_analyze"]
