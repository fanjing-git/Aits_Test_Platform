"""Focused tests for evidence-grounded screenshot recognition."""

from django.test import SimpleTestCase

from apps.requirement_analysis.screenshot_analyzer import analyze_screenshot_evidence


class ScreenshotAnalyzerTests(SimpleTestCase):
    """Ensure observations and test points retain screenshot evidence."""

    def test_controls_and_text_are_traceable(self) -> None:
        result = analyze_screenshot_evidence(
            [
                {"id": "ocr-1", "text": "全部", "location": {"left": 10, "top": 20}, "confidence": 0.98},
                {"id": "ocr-2", "text": "背包", "location": {"left": 30, "top": 50}, "confidence": 0.95},
            ],
            width=1920,
            height=1080,
            confidence=0.96,
        )
        self.assertEqual(len(result.elements), 2)
        self.assertEqual(result.elements[0]["type"], "control")
        self.assertEqual(result.regions[0]["bounds"]["width"], 1920)
        self.assertTrue(all(item["evidence_ids"] for item in result.test_points))

    def test_missing_evidence_is_explicitly_low_confidence(self) -> None:
        result = analyze_screenshot_evidence([], width=100, height=100, confidence=0.0)
        self.assertTrue(result.needs_confirmation)
        self.assertIn("未获得可验证", "".join(result.warnings))
        self.assertEqual(result.test_points, [])
