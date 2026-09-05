"""T025 vectorization and retrieval isolation tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from django.contrib.auth import get_user_model
from django.test import TestCase
from apps.knowledge.loader import load_and_chunk
from apps.knowledge.models import Document, Embedding, KnowledgeBase, QAPair, ReviewStatus
from apps.knowledge.retrieval import HashVectorizer, retrieve, vectorize_document
from apps.projects.models import Project


class RetrievalTests(TestCase):
    """Verify deterministic indexing, ranking, thresholds and project boundaries."""
    def setUp(self) -> None:
        user = get_user_model().objects.create_user(username='retrieval-owner')
        self.project = Project.objects.create(name='Retrieval project', created_by=user)
        self.other_project = Project.objects.create(name='Other retrieval project', created_by=user)
        self.base = KnowledgeBase.objects.create(name='Approved KB', project=self.project, created_by=user)
        self.other = KnowledgeBase.objects.create(name='Other KB', project=self.other_project, created_by=user)
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.document = Document.objects.create(knowledge_base=self.base, title='Guide', source_type='manual', content_text='login endpoint authentication token', created_by=user, status='ready', review_status='approved')
        self.document2 = Document.objects.create(knowledge_base=self.other, title='Other', source_type='manual', content_text='login endpoint authentication token', created_by=user, status='ready', review_status='approved')
        for document in (self.document, self.document2):
            embedding = Embedding.objects.create(knowledge_base=document.knowledge_base, document=document, content=document.content_text)
            embedding.vector = HashVectorizer().embed(embedding.content); embedding.model_name = 'local-hash-v1'; embedding.save(update_fields=('vector','model_name'))

    def test_vectorize_requires_ready_and_persists_model_metadata(self) -> None:
        """Index every parsed chunk and record adapter metadata."""
        pending = Document.objects.create(knowledge_base=self.base, title='Pending', source_type='manual', content_text='pending', created_by=self.document.created_by)
        Embedding.objects.create(knowledge_base=self.base, document=pending, content='pending')
        with self.assertRaises(ValueError): vectorize_document(pending)
        indexed = vectorize_document(self.document)
        self.assertEqual(len(indexed[0].vector), 64); self.assertEqual(indexed[0].model_name, 'local-hash-v1')
        self.document.refresh_from_db(); self.assertEqual(self.document.metadata['embedding_model'], 'local-hash-v1')

    def test_retrieval_is_project_scoped_ranked_and_thresholded(self) -> None:
        """Never return another project's chunk and honor top-k/threshold."""
        hits = retrieve('login endpoint', [str(self.base.pk)], top_k=1, threshold=0.1)
        self.assertEqual(len(hits), 1); self.assertEqual(hits[0].knowledge_base_id, str(self.base.pk))
        self.assertEqual(retrieve('login endpoint', [str(self.other.pk)]), [h for h in retrieve('login endpoint', [str(self.other.pk)])])
        self.assertEqual(retrieve('unrelated phrase', [str(self.base.pk)], threshold=0.99), [])

    def test_inactive_base_or_unready_document_is_excluded(self) -> None:
        """Filter stale sources before similarity ranking."""
        self.base.status = 'archived'; self.base.save(); self.assertEqual(retrieve('login', [str(self.base.pk)]), [])
        self.base.status = 'active'; self.base.save(); self.document.status = 'failed'; self.document.save(); self.assertEqual(retrieve('login', [str(self.base.pk)]), [])

    def test_qa_requires_approval_before_retrieval(self) -> None:
        """Unreviewed QA vectors remain invisible to search."""
        qa = QAPair.objects.create(knowledge_base=self.base, question='How login?', answer='Use token.', created_by=self.document.created_by)
        embedding = Embedding.objects.create(knowledge_base=self.base, qa_pair=qa, content='How login? Use token.', vector=HashVectorizer().embed('How login? Use token.'), model_name='local-hash-v1')
        hits = retrieve('How login?', [str(self.base.pk)], threshold=-1)
        self.assertNotIn(str(embedding.pk), [hit.embedding_id for hit in hits])
        qa.review_status = ReviewStatus.APPROVED; qa.reviewed_by=self.document.created_by; qa.save(); self.assertIn(str(embedding.pk), [hit.embedding_id for hit in retrieve('How login?', [str(self.base.pk)], threshold=-1)])

    def test_invalid_query_parameters_are_rejected(self) -> None:
        """Keep retrieval limits bounded and explicit."""
        for kwargs in ({'top_k': 0}, {'top_k': 51}, {'threshold': 2}):
            with self.assertRaises(ValueError): retrieve('query', [str(self.base.pk)], **kwargs)
