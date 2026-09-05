"""T027 knowledge API end-to-end and permission tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase
from apps.knowledge.models import Document, KnowledgeBase
from apps.projects.models import Project, ProjectMember


class KnowledgeAPITests(APITestCase):
    """Cover upload, parse, index, search, QA review and isolation."""
    def setUp(self) -> None:
        """Create manager, viewer and project-scoped knowledge base."""
        users=get_user_model(); self.owner=users.objects.create_user(username='api-knowledge-owner'); self.owner.profile.role='test_leader'; self.owner.profile.save(); self.viewer=users.objects.create_user(username='api-knowledge-viewer'); self.viewer.profile.role='viewer'; self.viewer.profile.save()
        self.project=Project.objects.create(name='API knowledge project',created_by=self.owner); ProjectMember.objects.create(project=self.project,user=self.owner,role='owner'); ProjectMember.objects.create(project=self.project,user=self.viewer,role='viewer'); self.base=KnowledgeBase.objects.create(name='API KB',project=self.project,created_by=self.owner); self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.settings=override_settings(KNOWLEDGE_DOCUMENT_ROOT=Path(self.temp.name),KNOWLEDGE_CHUNK_SIZE=40,KNOWLEDGE_CHUNK_OVERLAP=5); self.settings.enable(); self.addCleanup(self.settings.disable); self.client.force_authenticate(self.owner)

    def test_upload_parse_index_search_and_review(self) -> None:
        """Run the product's document pipeline and keep secrets out of responses."""
        response=self.client.post('/api/knowledge-documents/',{'knowledge_base':str(self.base.pk),'title':'Login guide','file':SimpleUploadedFile('guide.txt',b'login endpoint requires authentication token and secure cookie',content_type='text/plain')},format='multipart'); self.assertEqual(response.status_code,201,response.data); self.assertNotIn('file_path',response.data); document_id=response.data['id']; detail=f'/api/knowledge-documents/{document_id}/'; self.assertEqual(self.client.post(detail+'parse/').status_code,200); response=self.client.post(detail+'index/'); self.assertEqual(response.status_code,200,response.data); self.assertTrue(response.data['metadata']['embedding_model']); self.assertEqual(self.client.post(detail+'review/',{'decision':'approved','note':'checked'},format='json').status_code,200); self.assertEqual(self.client.get(detail).data['review_status'],'approved'); search=self.client.post('/api/knowledge-search/',{'query':'login authentication','knowledge_base_ids':[str(self.base.pk)]},format='json').data; self.assertTrue(search['results'])

    def test_project_isolation_and_viewer_read_only(self) -> None:
        """Viewer sees project assets but cannot mutate or review them."""
        other=Project.objects.create(name='Hidden API KB project',created_by=self.owner); KnowledgeBase.objects.create(name='Hidden',project=other,created_by=self.owner); self.client.force_authenticate(self.viewer); visible=self.client.get('/api/knowledge-bases/').data; self.assertEqual(len(visible),1); self.assertEqual(visible[0]['id'],str(self.base.pk)); self.assertEqual(self.client.post('/api/knowledge-bases/',{'project':str(other.pk),'name':'leak'},format='json').status_code,400); self.client.force_authenticate(self.owner); document=Document.objects.create(knowledge_base=self.base,title='Manual',source_type='manual',content_text='safe',created_by=self.owner); self.client.force_authenticate(self.viewer); self.assertEqual(self.client.patch(f'/api/knowledge-documents/{document.pk}/',{'title':'no'},format='json').status_code,403); self.assertEqual(self.client.post(f'/api/knowledge-documents/{document.pk}/review/',{'decision':'approved'},format='json').status_code,403); self.assertEqual(self.client.get('/api/knowledge-documents/').status_code,200)

    def test_invalid_upload_and_search_limits_are_actionable(self) -> None:
        """Reject unsupported files, malformed IDs and unsafe search bounds."""
        response=self.client.post('/api/knowledge-documents/',{'knowledge_base':str(self.base.pk),'title':'bad','file':SimpleUploadedFile('bad.exe',b'x')},format='multipart'); self.assertEqual(response.status_code,400); self.assertEqual(self.client.get('/api/knowledge-search/').status_code,405); self.assertEqual(self.client.post('/api/knowledge-search/',{'query':'x','top_k':51},format='json').status_code,400)

    def test_global_base_is_admin_only(self) -> None:
        """Shared knowledge collections do not leak to project members."""
        global_base=KnowledgeBase.objects.create(name='Built in',category='builtin',created_by=self.owner); self.assertEqual(self.client.get('/api/knowledge-bases/').data[0]['id'],str(self.base.pk)); self.assertEqual(self.client.get(f'/api/knowledge-bases/{global_base.pk}/').status_code,404)
