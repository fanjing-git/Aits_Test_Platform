from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from apps.projects.models import Project, ProjectMember
from apps.skills.models import Skill

class SkillRuntimeTests(APITestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='runtime-owner')
        project = Project.objects.create(name='runtime-project', created_by=user)
        ProjectMember.objects.create(project=project, user=user, role='owner')
        self.client.force_authenticate(user); self.skill = Skill.objects.create(project=project, category='custom', name='runtime-demo', input_schema={'type':'object','required':['url'],'properties':{'url':{'type':'string'}}}, output_schema={'type':'object'})
    def test_execute_validates_and_returns_structured_result(self):
        response = self.client.post(f'/api/skills/{self.skill.pk}/execute/', {'input': {'url':'https://example.test'}}, format='json')
        self.assertEqual(response.status_code, 200); self.assertEqual(response.data['status'], 'completed')
        response = self.client.post(f'/api/skills/{self.skill.pk}/execute/', {'input': {}}, format='json')
        self.assertEqual(response.status_code, 400); self.assertIn('required', response.data['detail'])
    def test_disabled_skill_cannot_execute(self):
        self.skill.status='disabled'; self.skill.save(update_fields=['status'])
        self.assertEqual(self.client.post(f'/api/skills/{self.skill.pk}/execute/', {'input': {}}, format='json').status_code, 400)
