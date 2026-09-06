"""Bounded, dependency-light parsers for requirement documents."""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from docx import Document as WordDocument
from pypdf import PdfReader

from apps.requirement_analysis.adapters import DocumentContent, SwaggerAdapter, adapter_for


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".pdf", ".docx", ".xlsx", ".json", ".png", ".jpg", ".jpeg", ".webp"})


class DocumentParseError(ValueError):
    """Raised when a requirement source cannot be safely parsed."""


@dataclass(frozen=True)
class ParsedDocument:
    """Normalized parser output shared by uploaded and online sources."""

    title: str
    content: str
    format: str
    source_type: str
    source_url: str = ""


def _normalize(text: str) -> str:
    """Normalize line endings and remove empty trailing whitespace."""
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def _bounded(content: bytes) -> bytes:
    if not content:
        raise DocumentParseError("文档内容不能为空。")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentParseError("文档超过10MB限制。")
    return content


def _parse_xlsx(content: bytes) -> str:
    """Extract visible cell values from XLSX XML without evaluating formulas."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(node.text or "" for node in item.iter() if node.tag.endswith("}t") or node.tag == "t") for item in root if item.tag.endswith("}si") or item.tag == "si"]
            sheets = sorted(name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
            rows: list[str] = []
            for sheet in sheets:
                root = ElementTree.fromstring(archive.read(sheet))
                for row in root.iter():
                    if not row.tag.endswith("}row") and row.tag != "row":
                        continue
                    values: list[str] = []
                    for cell in row:
                        if not cell.tag.endswith("}c") and cell.tag != "c":
                            continue
                        cell_type = cell.attrib.get("t", "")
                        value_node = next((child for child in cell if child.tag.endswith("}v") or child.tag == "v"), None)
                        inline_node = next((child for child in cell if child.tag.endswith("}is") or child.tag == "is"), None)
                        value = ""
                        if cell_type == "s" and value_node is not None:
                            index = int(value_node.text or "-1")
                            value = shared[index] if 0 <= index < len(shared) else ""
                        elif cell_type == "inlineStr" and inline_node is not None:
                            value = "".join(node.text or "" for node in inline_node.iter() if node.tag.endswith("}t") or node.tag == "t")
                        elif value_node is not None:
                            value = value_node.text or ""
                        values.append(value)
                    if any(values):
                        rows.append("\t".join(values))
            return _normalize("\n".join(rows))
    except (OSError, KeyError, ValueError, ElementTree.ParseError, zipfile.BadZipFile) as exc:
        raise DocumentParseError("Excel 文档解析失败，请检查文件内容。") from exc


def _parse_swagger(content: bytes) -> str:
    try:
        value = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentParseError("Swagger/OpenAPI 内容不是有效 JSON。") from exc
    if not isinstance(value, dict) or not (value.get("openapi") or value.get("swagger")):
        raise DocumentParseError("JSON 文档未声明 openapi 或 swagger 版本。")
    return json.dumps(value, ensure_ascii=False, indent=2)


def parse_document_bytes(content: bytes | bytearray, filename: str, *, source_url: str = "") -> ParsedDocument:
    """Parse an uploaded document by extension within the size and type boundary."""
    data = _bounded(bytes(content))
    suffix = Path(filename or "").suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise DocumentParseError("仅支持 PDF、Word、Excel、Markdown、Swagger、文本和图片文件。")
    try:
        if suffix in {".txt", ".md", ".markdown"}:
            text = _normalize(data.decode("utf-8-sig")); fmt = "markdown" if suffix != ".txt" else "text"
        elif suffix == ".pdf":
            text = _normalize("\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)); fmt = "pdf"
        elif suffix == ".docx":
            document = WordDocument(io.BytesIO(data))
            paragraphs = [paragraph.text for paragraph in document.paragraphs]
            tables = ["\t".join(cell.text for cell in row.cells) for table in document.tables for row in table.rows]
            text = _normalize("\n".join(paragraphs + tables)); fmt = "word"
        elif suffix == ".xlsx":
            text = _parse_xlsx(data); fmt = "excel"
        elif suffix == ".json":
            text = _parse_swagger(data); fmt = "swagger"
        else:
            try:
                from PIL import Image
                import pytesseract
                with Image.open(io.BytesIO(data)) as image:
                    text = _normalize(pytesseract.image_to_string(image))
            except ImportError as exc:
                raise DocumentParseError("图片 OCR 依赖未安装，暂时无法解析图片。") from exc
            fmt = "ocr"
    except DocumentParseError:
        raise
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise DocumentParseError("文档解析失败，请检查文件格式和内容。") from exc
    if not text:
        raise DocumentParseError("文档未提取到可用文本。")
    return ParsedDocument(Path(filename).stem or "需求文档", text, fmt, "file", source_url)


def parse_file(path: str | Path) -> ParsedDocument:
    """Read and parse a local file after enforcing the size boundary."""
    file_path = Path(path)
    try:
        if not file_path.is_file() or file_path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise DocumentParseError("文档不存在或超过10MB限制。")
        return parse_document_bytes(file_path.read_bytes(), file_path.name)
    except DocumentParseError:
        raise
    except OSError as exc:
        raise DocumentParseError("文档文件无法读取。") from exc


def parse_online(url: str) -> ParsedDocument:
    """Fetch through the existing provider adapter and normalize online content."""
    try:
        adapter = adapter_for(url)
        result: DocumentContent = adapter.fetch(url)
    except Exception as exc:  # noqa: BLE001 - hide network/provider details
        raise DocumentParseError("在线文档获取失败，请检查链接或稍后重试。") from exc
    fmt = "swagger" if isinstance(adapter, SwaggerAdapter) else "online"
    title = result.title or "在线文档"
    content = _normalize(result.content)
    if not content:
        raise DocumentParseError("在线文档未提取到可用文本。")
    return ParsedDocument(title, content, fmt, result.source_type, result.source_url)


def parse_requirement_document(document: Any) -> ParsedDocument:
    """Parse a persisted requirement source and advance it to the analysis stage."""
    document.status = document.Status.PARSING
    document.save(update_fields=("status",))
    try:
        if document.source_type == document.SourceType.ONLINE_LINK:
            parsed = parse_online(document.source_url)
        elif document.source_type == document.SourceType.FILE:
            parsed = parse_file(document.file_path)
        elif document.source_type == document.SourceType.MANUAL:
            parsed = parse_document_bytes(document.content_text.encode("utf-8"), f"{document.title}.md")
        else:
            raise DocumentParseError("暂不支持该需求文档来源类型。")
        document.content_text = parsed.content
        document.status = document.Status.ANALYZING
        document.save(update_fields=("content_text", "status"))
        return parsed
    except DocumentParseError:
        document.status = document.Status.FAILED
        document.save(update_fields=("status",))
        raise


__all__ = ["DocumentParseError", "MAX_DOCUMENT_BYTES", "ParsedDocument", "parse_document_bytes", "parse_file", "parse_online", "parse_requirement_document"]
