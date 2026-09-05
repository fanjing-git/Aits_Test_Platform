from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from apps.projects.models import Project, ProjectMember
from apps.skills.models import Skill

class SkillAPITests(APITestCase):
    def setUp(self):
        users = get_user_model(); self.owner = users.objects.create_user(username='skill-api-owner'); self.viewer = users.objects.create_user(username='skill-api-viewer')
        self.project = Project.objects.create(name='Skill API project', created_by=self.owner); ProjectMember.objects.create(project=self.project, user=self.owner, role='owner'); ProjectMember.objects.create(project=self.project, user=self.viewer, role='viewer')
        self.global_skill = Skill.objects.create(name='接口测试', triggers={'explicit':['接口']}, capabilities=[])
        self.client.force_authenticate(self.owner)
    def test_list_create_toggle_and_delete_custom_skill(self):
        self.assertEqual(self.client.get('/api/skills/').status_code, 200)
        response = self.client.post('/api/skills/', {'project':str(self.project.pk),'name':'项目技能','category':'custom','triggers':{},'capabilities':[],'tools':[],'knowledge':[],'input_schema':{},'output_schema':{}}, format='json')
        self.assertEqual(response.status_code, 201, response.data); skill_id=response.data['id']
        response = self.client.post(f'/api/skills/{skill_id}/toggle/'); self.assertEqual(response.data['status'], 'disabled')
        self.assertEqual(self.client.delete(f'/api/skills/{skill_id}/').status_code, 204)
    def test_viewer_can_read_project_skill_but_cannot_write(self):
        skill = Skill.objects.create(project=self.project, category='custom', name='只读技能')
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(f'/api/skills/{skill.pk}/').status_code, 200)
        self.assertEqual(self.client.patch(f'/api/skills/{skill.pk}/', {'description':'x'}, format='json').status_code, 403)
    def test_non_admin_cannot_create_global_skill_or_cross_project_skill(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.post('/api/skills/', {'name':'共享','category':'core','triggers':{},'capabilities':[],'tools':[],'knowledge':[],'input_schema':{},'output_schema':{}}, format='json').status_code, 400)
        other = Project.objects.create(name='Other skill project', created_by=self.owner)
        self.assertEqual(self.client.post('/api/skills/', {'project':str(other.pk),'name':'越权','category':'custom'}, format='json').status_code, 400)
    def test_anonymous_is_rejected(self):
        self.client.force_authenticate(None); self.assertEqual(self.client.get('/api/skills/').status_code, 401)
