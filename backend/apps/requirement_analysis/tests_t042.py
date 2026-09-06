"""Focused tests for requirement document parsing formats and safe failures."""
import io
import zipfile
from unittest.mock import patch

from docx import Document as WordDocument
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from pypdf import PdfWriter

from apps.requirement_analysis.adapters import DocumentContent
from apps.projects.models import Project
from apps.requirement_analysis.models import RequirementDocument
from apps.requirement_analysis.parser import DocumentParseError, parse_document_bytes, parse_online, parse_requirement_document


class RequirementParserTests(SimpleTestCase):
    """Cover the supported parser matrix without external services."""

    def test_markdown_word_pdf_and_swagger(self) -> None:
        markdown = parse_document_bytes(b"# Login\r\n\r\n- valid", "requirement.md")
        self.assertEqual(markdown.format, "markdown")
        self.assertEqual(markdown.content, "# Login\n\n- valid")

        word_stream = io.BytesIO()
        word = WordDocument(); word.add_paragraph("Word requirement"); word.save(word_stream)
        self.assertIn("Word requirement", parse_document_bytes(word_stream.getvalue(), "requirement.docx").content)

        pdf_stream = io.BytesIO()
        writer = PdfWriter(); writer.add_blank_page(width=200, height=200); writer.write(pdf_stream)
        with self.assertRaises(DocumentParseError): parse_document_bytes(pdf_stream.getvalue(), "blank.pdf")

        swagger = parse_document_bytes(b'{"openapi":"3.0.0","paths":{}}', "openapi.json")
        self.assertEqual(swagger.format, "swagger")
        self.assertIn('"openapi": "3.0.0"', swagger.content)

    def test_xlsx_values_and_rejected_types(self) -> None:
        workbook = io.BytesIO()
        with zipfile.ZipFile(workbook, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Feature</t></is></c><c r="B1"><v>42</v></c></row></sheetData></worksheet>')
        result = parse_document_bytes(workbook.getvalue(), "requirements.xlsx")
        self.assertIn("Feature\t42", result.content)
        with self.assertRaises(DocumentParseError): parse_document_bytes(b"binary", "requirements.xls")

    @patch("apps.requirement_analysis.parser.adapter_for")
    def test_online_content_is_normalized_and_provider_errors_are_safe(self, mocked_adapter) -> None:
        mocked_adapter.return_value.fetch.return_value = DocumentContent("Online", "a\r\nb", "online_link", "https://docs.example/a")
        result = parse_online("https://docs.example/a")
        self.assertEqual(result.content, "a\nb")
        mocked_adapter.return_value.fetch.side_effect = OSError("secret provider detail")
        with self.assertRaisesRegex(DocumentParseError, "在线文档获取失败"):
            parse_online("https://docs.example/a")

    def test_size_and_image_dependency_fail_closed(self) -> None:
        with self.assertRaisesRegex(DocumentParseError, "10MB"):
            parse_document_bytes(b"x" * (10 * 1024 * 1024 + 1), "large.txt")
        with self.assertRaisesRegex(DocumentParseError, "OCR"):
            parse_document_bytes(b"not-an-image", "screen.png")

    def test_text_parser_keeps_line_evidence(self) -> None:
        result = parse_document_bytes("# 登录\n用户提交账号。".encode("utf-8"), "requirement.md")
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual([item["location"]["line"] for item in result.evidence], [1, 2])
        self.assertEqual(result.evidence[1]["text"], "用户提交账号。")


class PersistedRequirementParserTests(TestCase):
    """Ensure parsing updates persisted document lifecycle state safely."""

    def test_manual_document_advances_to_analysis_and_failures_are_recorded(self) -> None:
        user = get_user_model().objects.create_user(username="parser-owner")
        project = Project.objects.create(name="Parser project", created_by=user)
        document = RequirementDocument.objects.create(project=project, title="Login", content_text="User can login", created_by=user)
        result = parse_requirement_document(document)
        self.assertEqual(result.content, "User can login")
        document.refresh_from_db()
        self.assertEqual(document.status, RequirementDocument.Status.ANALYZING)
        self.assertEqual(document.parse_confidence, 1.0)
        self.assertTrue(document.parse_evidence)

        screenshot_text = RequirementDocument.objects.create(project=project, title="Screenshot text", source_type=RequirementDocument.SourceType.SCREENSHOT, content_text="页面显示背包", created_by=user)
        parsed_screenshot = parse_requirement_document(screenshot_text)
        self.assertEqual(parsed_screenshot.content, "页面显示背包")

        broken = RequirementDocument.objects.create(project=project, title="Empty", content_text="", created_by=user)
        with self.assertRaises(DocumentParseError): parse_requirement_document(broken)
        broken.refresh_from_db()
        self.assertEqual(broken.status, RequirementDocument.Status.FAILED)
