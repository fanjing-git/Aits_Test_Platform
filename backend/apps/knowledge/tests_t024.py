"""T024 parser and chunking tests using local disposable files."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from docx import Document as WordDocument
from pypdf import PdfWriter
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from apps.knowledge.loader import DocumentLoadError, chunk_text, load_and_chunk, load_text
from apps.knowledge.models import Document, Embedding, KnowledgeBase
from apps.projects.models import Project


class DocumentLoaderTests(TestCase):
    """Verify supported formats, limits, path boundaries and idempotent chunks."""
    def setUp(self) -> None:
        user = get_user_model().objects.create_user(username='loader-owner')
        project = Project.objects.create(name='Loader project', created_by=user)
        self.base = KnowledgeBase.objects.create(name='Loader KB', project=project, created_by=user)
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = override_settings(KNOWLEDGE_DOCUMENT_ROOT=self.root, KNOWLEDGE_DOCUMENT_MAX_BYTES=1024 * 1024, KNOWLEDGE_CHUNK_SIZE=20, KNOWLEDGE_CHUNK_OVERLAP=5)
        self.settings.enable(); self.addCleanup(self.settings.disable)

    def document(self, filename: str, source_type: str = 'file') -> Document:
        return Document.objects.create(knowledge_base=self.base, title=filename, source_type=source_type, file_path=str(self.root / filename), created_by=self.base.created_by)

    def test_txt_markdown_and_chunk_boundaries(self) -> None:
        """Normalize UTF-8 BOM/newlines and produce bounded overlap."""
        (self.root / 'notes.md').write_text('\ufeffalpha beta gamma\r\ndelta epsilon zeta', encoding='utf-8')
        document = self.document('notes.md')
        loaded = load_text(document)
        self.assertTrue(loaded.startswith('alpha beta gamma'))
        self.assertNotIn('\ufeff', loaded)
        self.assertNotIn('\r', loaded)
        chunks = chunk_text(load_text(document), size=20, overlap=5)
        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks)); self.assertGreater(len(chunks), 1)
        self.assertTrue(any(set(chunks[i]) & set(chunks[i + 1]) for i in range(len(chunks) - 1)))

    def test_docx_and_pdf_extract_text(self) -> None:
        """Extract paragraph/page text through the pinned parser libraries."""
        word = WordDocument(); word.add_paragraph('Word source text'); word.save(self.root / 'source.docx')
        self.assertIn('Word source text', load_text(self.document('source.docx')))
        writer = PdfWriter(); writer.add_blank_page(width=200, height=200); writer.write(self.root / 'blank.pdf')
        self.assertEqual(load_text(self.document('blank.pdf')), '')

    def test_load_and_chunk_sets_status_replaces_old_chunks(self) -> None:
        """Persist ready status and idempotently replace prior chunk records."""
        (self.root / 'source.txt').write_text('one two three four five six seven eight nine ten', encoding='utf-8')
        document = self.document('source.txt')
        first = load_and_chunk(document); second = load_and_chunk(document)
        self.assertEqual(len(first), len(second)); self.assertEqual(document.__class__.objects.get(pk=document.pk).status, 'ready')
        self.assertEqual(Embedding.objects.filter(document=document).count(), len(second))
        self.assertEqual(list(Embedding.objects.filter(document=document).values_list('chunk_index', flat=True)), list(range(len(second))))
        self.assertEqual(document.__class__.objects.get(pk=document.pk).metadata['chunk_count'], len(second))

    def test_unsupported_missing_oversize_and_empty_are_safe_failures(self) -> None:
        """Reject unsafe paths, unsupported extensions, oversized and empty files."""
        cases = [('missing.txt', None), ('outside.txt', self.root.parent / 'outside.txt'), ('bad.exe', self.root / 'bad.exe'), ('empty.txt', self.root / 'empty.txt'), ('large.txt', self.root / 'large.txt')]
        (self.root / 'bad.exe').write_text('x'); (self.root / 'empty.txt').write_text(''); (self.root / 'large.txt').write_text('x' * (2 * 1024 * 1024))
        for filename, actual in cases:
            if actual and actual != self.root / filename: actual.write_text('outside')
            document = self.document(filename)
            with self.subTest(filename=filename), self.assertRaises(DocumentLoadError): load_and_chunk(document)
            self.assertEqual(Document.objects.get(pk=document.pk).status, 'failed')

    def test_invalid_chunk_configuration_and_binary_text_are_rejected(self) -> None:
        """Prevent infinite loops and malformed text from entering embeddings."""
        with self.assertRaises(ValueError): chunk_text('text', size=5, overlap=5)
        (self.root / 'binary.txt').write_bytes(b'\xff\xfe')
        with self.assertRaises(DocumentLoadError): load_text(self.document('binary.txt'))
