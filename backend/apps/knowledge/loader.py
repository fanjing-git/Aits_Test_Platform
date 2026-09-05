"""Safe local document loading and deterministic text chunking."""
from pathlib import Path
from typing import Iterable
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from docx import Document as WordDocument
from pypdf import PdfReader
from apps.knowledge.models import Document, Embedding


class DocumentLoadError(ValueError):
    """Indicate an unsupported, inaccessible or malformed source document."""


def _safe_path(document: Document) -> Path:
    """Resolve a document path under the configured upload root."""
    if not document.file_path:
        raise DocumentLoadError("文档未提供文件路径。")
    path = Path(document.file_path).expanduser().resolve()
    root = Path(settings.KNOWLEDGE_DOCUMENT_ROOT).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DocumentLoadError("文档路径不在允许的知识库目录内。") from exc
    if not path.is_file():
        raise DocumentLoadError("文档文件不存在。")
    if path.stat().st_size > settings.KNOWLEDGE_DOCUMENT_MAX_BYTES:
        raise DocumentLoadError("文档超过允许的大小限制。")
    return path


def load_text(document: Document) -> str:
    """Extract text from TXT/Markdown, PDF or DOCX without executing content."""
    path = _safe_path(document)
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md", ".markdown"}:
            return path.read_text(encoding="utf-8-sig")
        if suffix == ".pdf":
            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        if suffix == ".docx":
            return "\n".join(paragraph.text for paragraph in WordDocument(str(path)).paragraphs)
    except (OSError, ValueError, TypeError) as exc:
        raise DocumentLoadError("文档解析失败，请检查文件格式和内容。") from exc
    raise DocumentLoadError("仅支持 TXT、Markdown、PDF 和 DOCX 文件。")


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split normalized text into bounded overlapping chunks."""
    chunk_size = size or settings.KNOWLEDGE_CHUNK_SIZE
    chunk_overlap = settings.KNOWLEDGE_CHUNK_OVERLAP if overlap is None else overlap
    if chunk_size <= 0 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("分块大小和重叠长度配置无效。")
    normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        if end < len(normalized):
            boundary = max(normalized.rfind("\n", start, end), normalized.rfind(" ", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary
        value = normalized[start:end].strip()
        if value:
            chunks.append(value)
        if end >= len(normalized):
            break
        start = max(start + 1, end - chunk_overlap)
    return chunks


def load_and_chunk(document: Document) -> list[Embedding]:
    """Parse one document, replace its chunks and update parsing status atomically."""
    document.status = Document.Status.PARSING
    document.save(update_fields=("status", "updated_at"))
    try:
        chunks = chunk_text(load_text(document))
        if not chunks:
            raise DocumentLoadError("文档未提取到可用文本。")
        with transaction.atomic():
            document.content_text = "\n\n".join(chunks)
            document.status = Document.Status.READY
            document.metadata = {**document.metadata, "chunk_count": len(chunks), "chunk_size": settings.KNOWLEDGE_CHUNK_SIZE, "chunk_overlap": settings.KNOWLEDGE_CHUNK_OVERLAP}
            document.save(update_fields=("content_text", "status", "metadata", "updated_at"))
            document.embeddings.all().delete()
            embeddings = [Embedding(knowledge_base=document.knowledge_base, document=document, chunk_index=index, content=value, metadata={"source_document_id": str(document.pk)}) for index, value in enumerate(chunks)]
            Embedding.objects.bulk_create(embeddings)
            return embeddings
    except DocumentLoadError:
        document.status = Document.Status.FAILED
        document.metadata = {**document.metadata, "error": "文档解析失败。"}
        document.save(update_fields=("status", "metadata", "updated_at"))
        raise
    except Exception as exc:  # noqa: BLE001 - sanitize parser/library failures
        document.status = Document.Status.FAILED
        document.metadata = {**document.metadata, "error": "文档解析失败。"}
        document.save(update_fields=("status", "metadata", "updated_at"))
        raise DocumentLoadError("文档解析失败，请检查文件格式和内容。") from exc
