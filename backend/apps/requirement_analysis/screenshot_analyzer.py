"""Evidence-first screenshot analysis with a safe local fallback."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from apps.requirement_analysis.parser import DocumentParseError, _parse_image


@dataclass(frozen=True)
class ScreenshotAnalysisResult:
    """Structured screenshot observations and their testable implications."""

    elements: list[dict[str, Any]]
    text_blocks: list[dict[str, Any]]
    regions: list[dict[str, Any]]
    test_points: list[dict[str, Any]]
    confidence: float
    warnings: list[str]
    needs_confirmation: bool

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible report."""
        return {
            "elements": self.elements,
            "text_blocks": self.text_blocks,
            "regions": self.regions,
            "test_points": self.test_points,
            "confidence": self.confidence,
            "warnings": self.warnings,
            "needs_confirmation": self.needs_confirmation,
            "method": "ocr_evidence_and_geometry",
        }


def analyze_screenshot_evidence(
    evidence: Sequence[Mapping[str, Any]],
    *,
    width: int = 0,
    height: int = 0,
    confidence: float = 0.0,
    warnings: Sequence[str] = (),
) -> ScreenshotAnalysisResult:
    """Build only observations grounded in OCR boxes or image geometry."""
    text_blocks: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    for item in evidence:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        location = item.get("location", {})
        block = {"evidence_id": str(item.get("id", "")), "text": text, "location": location, "confidence": float(item.get("confidence", 0.0) or 0.0)}
        text_blocks.append(block)
        lowered = text.casefold()
        element_type = "text"
        if any(token in lowered for token in ("按钮", "确定", "取消", "返回", "button", "tab", "菜单", "全部", "最近", "材料", "强化")):
            element_type = "control"
        elements.append({**block, "type": element_type, "interaction": "可点击或切换" if element_type == "control" else "不可由OCR确认交互"})

    regions: list[dict[str, Any]] = []
    if width > 0 and height > 0:
        regions.append({"id": "region-full-screen", "kind": "screen", "bounds": {"left": 0, "top": 0, "width": width, "height": height}, "evidence_ids": [str(item.get("id", "")) for item in evidence]})
    report_warnings = [str(item) for item in warnings if str(item).strip()]
    if not text_blocks:
        report_warnings.append("未获得可验证的 OCR 文字证据，无法确认具体业务功能。")
    needs_confirmation = confidence < 0.75 or bool(report_warnings)
    test_points: list[dict[str, Any]] = []
    for index, element in enumerate(elements, start=1):
        test_points.append({"id": f"screenshot-test-{index}", "scenario": "元素可见性", "description": f"确认截图中的“{element['text']}”在目标页面可见且位置一致。", "evidence_ids": [element["evidence_id"]], "needs_confirmation": needs_confirmation})
        if element["type"] == "control":
            test_points.append({"id": f"screenshot-test-{len(test_points)+1}", "scenario": "控件交互", "description": f"确认“{element['text']}”的点击或切换行为与产品定义一致。", "evidence_ids": [element["evidence_id"]], "needs_confirmation": True})
    return ScreenshotAnalysisResult(elements, text_blocks, regions, test_points, round(max(0.0, min(1.0, confidence)), 4), report_warnings, needs_confirmation)


def analyze_screenshot(content: bytes) -> ScreenshotAnalysisResult:
    """Run local OCR and geometry analysis without calling external services."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as image:
            text, evidence, confidence, warnings = _parse_image(content)
            return analyze_screenshot_evidence(evidence, width=image.width, height=image.height, confidence=confidence, warnings=warnings)
    except DocumentParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - sanitize image library failures
        raise DocumentParseError("截图识别失败，请检查图片和 OCR 配置。") from exc


def analyze_screenshot_file(path: str | Path) -> ScreenshotAnalysisResult:
    """Read one bounded local image and return its evidence report."""
    file_path = Path(path)
    try:
        return analyze_screenshot(file_path.read_bytes())
    except OSError as exc:
        raise DocumentParseError("截图文件无法读取。") from exc


__all__ = ["ScreenshotAnalysisResult", "analyze_screenshot", "analyze_screenshot_evidence", "analyze_screenshot_file"]
