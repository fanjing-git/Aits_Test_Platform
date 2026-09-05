"""T023 knowledge model and review-boundary tests."""
import os
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from apps.knowledge.models import Document, Embedding, KnowledgeBase, QAPair, ReviewStatus
from apps.projects.models import Project

class KnowledgeModelTests(TestCase):
    """Verify knowledge scope, source validation and review lifecycle."""
    def setUp(self) -> None:
        """Create projects and users for isolation assertions."""
        patcher = patch.dict(os.environ, {'MODEL_CONFIG_FERNET_KEY': Fernet.generate_key().decode()}); patcher.start(); self.addCleanup(patcher.stop)
        self.user = get_user_model().objects.create_user(username='knowledge-owner')
        self.reviewer = get_user_model().objects.create_user(username='knowledge-reviewer')
        self.project = Project.objects.create(name='Knowledge project', created_by=self.user)
        self.other = Project.objects.create(name='Other knowledge project', created_by=self.user)
        self.base = KnowledgeBase.objects.create(name='Project KB', project=self.project, created_by=self.user)

    def test_categories_and_scope_rules(self) -> None:
        """Allow shared categories while enforcing project/personal semantics."""
        self.assertEqual(self.base.status, 'active')
        self.assertEqual(KnowledgeBase.objects.create(name='Built in', category='builtin', created_by=self.user).project, None)
        for category, project in (('project', None), ('personal', self.project)):
            with self.subTest(category=category):
                with self.assertRaises(ValidationError): KnowledgeBase(name='bad', category=category, project=project, created_by=self.user).full_clean()

    def test_document_source_validation_and_status(self) -> None:
        """Require source fields appropriate to manual, URL and file documents."""
        doc = Document.objects.create(knowledge_base=self.base, title='Manual', source_type='manual', content_text='text', created_by=self.user)
        self.assertEqual(doc.status, 'uploaded')
        for source_type, field in (('manual', 'content_text'), ('online_link', 'source_url'), ('file', 'file_path')):
            kwargs = {'source_type': source_type, field: ''}
            with self.subTest(source_type=source_type), self.assertRaises(ValidationError): Document(knowledge_base=self.base, title='bad', created_by=self.user, **kwargs).full_clean()

    def test_qa_review_and_source_project_boundary(self) -> None:
        """Approved content records a reviewer and cannot cross knowledge bases."""
        doc = Document.objects.create(knowledge_base=self.base, title='Manual', source_type='manual', content_text='text', created_by=self.user)
        qa = QAPair(knowledge_base=self.base, question='Q', answer='A', source_document=doc, created_by=self.user, review_status=ReviewStatus.APPROVED)
        with self.assertRaises(ValidationError): qa.full_clean()
        qa.reviewed_by = self.reviewer; qa.full_clean(); qa.save(); self.assertEqual(qa.review_status, 'approved')
        other = KnowledgeBase.objects.create(name='Other', project=self.other, created_by=self.user)
        qa.knowledge_base = other
        with self.assertRaises(ValidationError): qa.full_clean()

    def test_embedding_requires_one_source_and_same_base(self) -> None:
        """Reject ambiguous, empty and cross-base vector provenance."""
        doc = Document.objects.create(knowledge_base=self.base, title='Manual', source_type='manual', content_text='text', created_by=self.user)
        for kwargs in ({}, {'document':doc, 'qa_pair':QAPair(knowledge_base=self.base, question='Q', answer='A', created_by=self.user)}, {'document':doc, 'vector':[]}, {'document':doc, 'vector':['bad']}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError): Embedding(knowledge_base=self.base, content='chunk', **kwargs).full_clean()
        emb = Embedding(knowledge_base=self.base, document=doc, content='chunk', vector=[0.1, -0.2], model_name='mock')
        emb.full_clean(); emb.save()
        self.assertEqual(emb.vector, [0.1, -0.2])
        with self.assertRaises(IntegrityError), transaction.atomic(): Embedding.objects.create(knowledge_base=self.base, document=doc, content='duplicate', vector=[0.3])

    def test_json_metadata_is_object_and_delete_cascades(self) -> None:
        """Keep metadata strict and remove child assets with their base."""
        with self.assertRaises(ValidationError): KnowledgeBase(name='bad', project=self.project, created_by=self.user, metadata=[]).full_clean()
        Document.objects.create(knowledge_base=self.base, title='Manual', source_type='manual', content_text='text', created_by=self.user)
        self.base.delete(); self.assertFalse(Document.objects.filter(knowledge_base_id=self.base.id).exists())
