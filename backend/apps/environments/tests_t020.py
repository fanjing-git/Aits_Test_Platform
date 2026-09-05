"""Environment REST contract and permission regression tests."""
import os
from unittest.mock import patch
from uuid import uuid4
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from apps.environments.models import Environment
from apps.projects.models import Project, ProjectMember


class EnvironmentAPITests(APITestCase):
    """Cover CRUD, secret handling, platform roles and project isolation."""

    def setUp(self) -> None:
        """Create an isolated role matrix and temporary cryptographic key."""
        key_patch = patch.dict(os.environ, {"MODEL_CONFIG_FERNET_KEY": Fernet.generate_key().decode()})
        key_patch.start()
        self.addCleanup(key_patch.stop)
        self.users = {}
        for role in ("admin", "test_leader", "tester", "developer", "viewer"):
            user = get_user_model().objects.create_user(username='env-' + role)
            user.profile.role = role
            user.profile.save()
            self.users[role] = user
        self.project = Project.objects.create(name='API environment project', created_by=self.users['test_leader'])
        for role, user in self.users.items():
            if role != 'admin':
                ProjectMember.objects.create(project=self.project, user=user, role='owner' if role == 'test_leader' else 'manager')
        self.other = Project.objects.create(name='Hidden project', created_by=self.users['admin'])
        self.url = '/api/environments/'
        self.payload = {'project_id': str(self.project.pk), 'name': 'test', 'base_url': 'https://example.com', 'auth_config': {'token': 'fake-token'}, 'database_config': {'password': 'fake-password'}, 'variables': {'secret': 'fake-variable'}}
        self.client.force_authenticate(self.users['test_leader'])

    def test_crud_preserves_omitted_secrets_and_allows_explicit_clear(self) -> None:
        """Expose metadata only through create, list, retrieve and patch."""
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        detail = self.url + str(response.data['id']) + '/'
        for data in (response.data, self.client.get(self.url).data[0], self.client.get(detail).data):
            for field in ('auth_config', 'database_config', 'variables'):
                self.assertNotIn(field, data)
                self.assertTrue(data['has_' + field])
            self.assertNotIn('fake-token', str(data))
        response = self.client.patch(detail, {'description': 'updated'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        env = Environment.objects.get(pk=response.data['id'])
        self.assertEqual(env.auth_config, {'token': 'fake-token'})
        self.assertEqual(self.client.patch(detail, {'auth_config': {}}, format='json').status_code, 200)
        env.refresh_from_db()
        self.assertEqual(env.auth_config, {})
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertFalse(Environment.objects.filter(pk=env.pk).exists())

    def test_platform_role_write_matrix(self) -> None:
        """Project management alone cannot bypass platform capabilities."""
        env = Environment.objects.create(project=self.project, name='dev', base_url='https://example.com')
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, 200)
                expected = 200 if role in ('admin', 'test_leader') else 403
                self.assertEqual(self.client.patch(f'{self.url}{env.pk}/', {'description': role}, format='json').status_code, expected)
                if expected == 403:
                    self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 403)
                    self.assertEqual(self.client.delete(f'{self.url}{env.pk}/').status_code, 403)

    def test_leader_requires_project_management_role(self) -> None:
        """Read-only project memberships stay read-only for test leaders."""
        ProjectMember.objects.filter(project=self.project, user=self.users['test_leader']).update(role='viewer')
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 403)

    def test_cross_project_resources_and_create_are_hidden(self) -> None:
        """Do not reveal another project's environment names or existence."""
        env = Environment.objects.create(project=self.other, name='test', base_url='https://example.com')
        self.assertEqual(self.client.get(self.url).data, [])
        for method in ('get', 'patch', 'delete'):
            response = getattr(self.client, method)(f'{self.url}{env.pk}/')
            self.assertEqual(response.status_code, 404)
        for project_id in (str(self.other.pk), str(uuid4())):
            payload = {**self.payload, 'project_id': project_id}
            self.assertEqual(self.client.post(self.url, payload, format='json').status_code, 404)

    def test_duplicate_and_invalid_inputs_return_400(self) -> None:
        """Normalize model validation instead of producing server errors."""
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 201)
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 400)
        for overrides in ({'project_id': 'bad'}, {'name': 'qa'}, {'auth_config': []}, {'database_config': None}, {'variables': ''}, {'base_url': 'ftp://example.com'}, {'base_url': 'https://user:pass@example.com'}, {'health_status': 'healthy'}):
            with self.subTest(overrides=overrides):
                response = self.client.post(self.url, {**self.payload, 'name': 'dev', **overrides}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.client.get(self.url, {'project': 'bad'}).status_code, 400)
        self.assertEqual(self.client.get(self.url + 'bad/').status_code, 404)

    def test_admin_cannot_move_environment_or_forge_health(self) -> None:
        """Protect isolation and probe-owned fields even from configuration editors."""
        env = Environment.objects.create(project=self.project, name='test', base_url='https://example.com')
        self.client.force_authenticate(self.users['admin'])
        for changes in ({'project_id': str(self.other.pk)}, {'health_status': 'healthy'}):
            self.assertEqual(self.client.patch(f'{self.url}{env.pk}/', changes, format='json').status_code, 400)

    def test_anonymous_is_401_and_filter_is_project_scoped(self) -> None:
        """Unauthenticated callers cannot read or write environments."""
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.post(self.url, self.payload, format='json').status_code, 401)
        self.client.force_authenticate(self.users['admin'])
        self.client.post(self.url, self.payload, format='json')
        self.assertEqual(len(self.client.get(self.url, {'project': str(self.project.pk)}).data), 1)
        self.assertEqual(self.client.get(self.url, {'project': str(self.other.pk)}).data, [])

    def test_wrong_key_returns_safe_service_error(self) -> None:
        """Report encryption failures without exposing key material or payloads."""
        self.client.post(self.url, self.payload, format='json')
        with patch.dict(os.environ, {'MODEL_CONFIG_FERNET_KEY': Fernet.generate_key().decode()}):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('fake-token', str(response.data))
