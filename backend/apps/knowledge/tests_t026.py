"""T026 review workflow and retrieval approval gates."""
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied
from apps.knowledge.models import Document, KnowledgeBase, QAPair, ReviewStatus
from apps.knowledge.review import review_asset
from apps.knowledge.retrieval import HashVectorizer, retrieve
from apps.projects.models import Project, ProjectMember


class ReviewWorkflowTests(TestCase):
    """Cover review transitions, authorization and audit fields."""
    def setUp(self) -> None:
        """Create owner, manager, viewer and project knowledge."""
        users = get_user_model()
        self.owner = users.objects.create_user(username='review-owner'); self.owner.profile.role = 'test_leader'; self.owner.profile.save()
        self.viewer = users.objects.create_user(username='review-viewer'); self.viewer.profile.role = 'viewer'; self.viewer.profile.save()
        self.project = Project.objects.create(name='Review project', created_by=self.owner)
        ProjectMember.objects.create(project=self.project, user=self.owner, role='owner')
        ProjectMember.objects.create(project=self.project, user=self.viewer, role='viewer')
        self.base = KnowledgeBase.objects.create(name='Review KB', project=self.project, created_by=self.owner)
        self.document = Document.objects.create(knowledge_base=self.base, title='Review doc', source_type='manual', content_text='reviewable content', created_by=self.owner, status='ready')
        embedding = self.document.embeddings.create(knowledge_base=self.base, content=self.document.content_text, vector=HashVectorizer().embed(self.document.content_text), model_name='local-hash-v1')
        self.qa = QAPair.objects.create(knowledge_base=self.base, question='Question', answer='Answer', created_by=self.owner)
        self.qa_embedding = self.qa.embeddings.create(knowledge_base=self.base, content='Question Answer', vector=HashVectorizer().embed('Question Answer'), model_name='local-hash-v1')

    def test_document_approval_records_reviewer_and_makes_retrievable(self) -> None:
        """Approval unlocks document chunks and stores an audit timestamp."""
        self.assertEqual(retrieve('reviewable', [str(self.base.pk)], threshold=-1), [])
        result = review_asset(self.document, self.owner, 'approved', 'checked source')
        self.assertEqual(result.review_status, ReviewStatus.APPROVED); self.assertEqual(result.reviewed_by_id, self.owner.pk); self.assertTrue(result.reviewed_at); self.assertEqual(result.review_note, 'checked source')
        self.assertTrue(retrieve('reviewable', [str(self.base.pk)], threshold=-1))

    def test_reject_pause_and_invalid_transition(self) -> None:
        """Non-pending decisions remain auditable and pending is not a reset."""
        for decision in ('rejected', 'paused'):
            result = review_asset(self.document, self.owner, decision)
            self.assertEqual(result.review_status, decision)
        with self.assertRaises(ValidationError): review_asset(self.document, self.owner, 'pending')
        with self.assertRaises(ValidationError): review_asset(self.document, self.owner, 'unknown')
        with self.assertRaises(ValidationError): review_asset(self.document, self.owner, 'approved', 'x' * 501)

    def test_viewer_cannot_review_and_project_boundary_is_enforced(self) -> None:
        """Read-only project members cannot alter review decisions."""
        with self.assertRaises(PermissionDenied): review_asset(self.document, self.viewer, 'approved')
        other_project = Project.objects.create(name='Other review project', created_by=self.owner)
        other_base = KnowledgeBase.objects.create(name='Other KB', project=other_project, created_by=self.owner)
        other_doc = Document.objects.create(knowledge_base=other_base, title='Other', source_type='manual', content_text='x', created_by=self.owner)
        with self.assertRaises(PermissionDenied): review_asset(other_doc, self.owner, 'approved')

    def test_qa_approval_unlocks_qa_and_reject_keeps_it_hidden(self) -> None:
        """QA review uses the existing reviewer fields and retrieval gate."""
        self.assertNotIn(str(self.qa_embedding.pk), [hit.embedding_id for hit in retrieve('Question', [str(self.base.pk)], threshold=-1)])
        review_asset(self.qa, self.owner, 'approved')
        self.assertIn(str(self.qa_embedding.pk), [hit.embedding_id for hit in retrieve('Question', [str(self.base.pk)], threshold=-1)])
        review_asset(self.qa, self.owner, 'rejected')
        self.assertNotIn(str(self.qa_embedding.pk), [hit.embedding_id for hit in retrieve('Question', [str(self.base.pk)], threshold=-1)])

    def test_approved_requires_review_actor_and_document_status(self) -> None:
        """Approval does not bypass parsing readiness."""
        self.document.status = 'parsing'; self.document.save()
        with self.assertRaises(ValidationError): review_asset(self.document, self.owner, 'approved')
