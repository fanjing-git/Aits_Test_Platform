from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.projects.models import Project
from apps.requirement_analysis.models import RequirementAnalysis, RequirementDocument

class RequirementModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='requirement-owner')
        self.project = Project.objects.create(name='Requirement project', created_by=self.user)
    def test_document_and_analysis_are_project_scoped(self):
        document = RequirementDocument.objects.create(project=self.project, title='登录需求', content_text='用户可以登录', created_by=self.user)
        analysis = RequirementAnalysis.objects.create(document=document, modules=['auth'], functions=['login'], linkages=[], test_points=['invalid password'], coverage_report={'rate': 1})
        self.assertIn('登录需求', str(document)); self.assertEqual(analysis.document.project, self.project)
    def test_source_specific_requirements_are_validated(self):
        with self.assertRaises(ValidationError): RequirementDocument(project=self.project, title='链接', source_type='online_link', created_by=self.user).full_clean()
        with self.assertRaises(ValidationError): RequirementDocument(project=self.project, title='手工', source_type='manual', content_text='', created_by=self.user).full_clean()
        with self.assertRaises(ValidationError): RequirementAnalysis(document=RequirementDocument(project=self.project, title='x', content_text='x', created_by=self.user), modules={}, functions=[], linkages=[], test_points=[], coverage_report={}).full_clean()
