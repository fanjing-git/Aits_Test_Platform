"""Health probe outcomes, network boundaries and race protection."""
import os
from unittest.mock import MagicMock, patch
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
import requests
from apps.environments.models import Environment
from apps.environments.health import HealthResult, StaleHealthCheck, check_environment, probe_endpoint
from apps.environments.services import save_environment
from apps.projects.models import Project, ProjectMember


@override_settings(ENVIRONMENT_HEALTH_ALLOWED_ORIGINS=('https://health.example.com',))
class HealthCheckTests(APITestCase):
    """Use fake responses exclusively for automated health checks."""

    def setUp(self) -> None:
        """Create disposable key, manager and environment."""
        key_patch = patch.dict(os.environ, {'MODEL_CONFIG_FERNET_KEY': Fernet.generate_key().decode()})
        key_patch.start()
        self.addCleanup(key_patch.stop)
        self.user = get_user_model().objects.create_user(username='health-admin')
        self.user.profile.role = 'admin'
        self.user.profile.save()
        self.project = Project.objects.create(name='Health project', created_by=self.user)
        self.env = Environment.objects.create(project=self.project, name='test', base_url='https://health.example.com', health_check_url='https://health.example.com/health')
        self.url = f'/api/environments/{self.env.pk}/health-check/'
        self.client.force_authenticate(self.user)

    def test_http_success_error_and_redirect_are_not_followed(self) -> None:
        """Accept only 2xx; do not read response bodies or forward secrets."""
        for code in (200, 204, 302, 401, 500):
            with self.subTest(code=code), patch('apps.environments.health.requests.Session') as session_type:
                session = session_type.return_value.__enter__.return_value
                response = session.get.return_value.__enter__.return_value
                response.status_code = code
                result = probe_endpoint(self.env.health_check_url)
                self.assertEqual(result.ok, 200 <= code < 300)
                self.assertFalse(session.trust_env)
                self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
                self.assertEqual(session.get.call_args.kwargs['timeout'], (2, 3))
                self.assertNotIn('Authorization', session.get.call_args.kwargs['headers'])
                response.json.assert_not_called()

    def test_timeout_and_connection_failure_are_sanitized(self) -> None:
        """Never return request exceptions containing sensitive URL content."""
        for exc in (requests.Timeout('private-token'), requests.ConnectionError('private-token')):
            with patch('apps.environments.health.requests.Session') as session_type:
                session_type.return_value.__enter__.return_value.get.side_effect = exc
                result = probe_endpoint(self.env.health_check_url)
                self.assertFalse(result.ok)
                self.assertNotIn('private-token', result.message)

    def test_unapproved_origin_and_missing_url_do_not_request(self) -> None:
        """Configuration errors preserve the old health result."""
        with patch('apps.environments.health.requests.Session') as session:
            for url in ('', 'https://other.example.com/health', 'https://health.example.com:444/health', 'http://health.example.com/health'):
                Environment.objects.filter(pk=self.env.pk).update(health_check_url=url)
                response = self.client.post(self.url)
                self.assertEqual(response.status_code, 400, response.data)
            session.assert_not_called()

    def test_fail_then_recover_and_record_timestamp(self) -> None:
        """Update availability and health with safe persisted metadata."""
        for ok, status in ((False, 'unavailable'), (True, 'available')):
            with patch('apps.environments.health.probe_endpoint', return_value=HealthResult(ok, 'safe result', 12)):
                response = self.client.post(self.url)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['status'], status)
                self.assertEqual(response.data['health_status'], 'healthy' if ok else 'unhealthy')
                self.assertTrue(response.data['health_checked_at'])
                self.assertEqual(response.data['health_latency_ms'], 12)
                self.assertNotIn('auth_config', response.data)

    def test_maintenance_is_preserved_for_both_outcomes(self) -> None:
        """A probe cannot cancel an operator's maintenance window."""
        Environment.objects.filter(pk=self.env.pk).update(status='maintenance')
        for ok in (False, True):
            with patch('apps.environments.health.probe_endpoint', return_value=HealthResult(ok, 'safe', 1)):
                self.assertEqual(self.client.post(self.url).data['status'], 'maintenance')

    def test_permission_and_isolation_precede_network(self) -> None:
        """Anonymous, viewer and cross-project calls must never probe."""
        with patch('apps.environments.health.probe_endpoint') as probe:
            self.client.force_authenticate(None)
            self.assertEqual(self.client.post(self.url).status_code, 401)
            reader = get_user_model().objects.create_user(username='health-reader')
            self.client.force_authenticate(reader)
            self.assertEqual(self.client.post(self.url).status_code, 404)
            ProjectMember.objects.create(project=self.project, user=reader, role='viewer')
            self.assertEqual(self.client.post(self.url).status_code, 403)
            probe.assert_not_called()

    def test_stale_result_after_edit_is_discarded(self) -> None:
        """Changing configuration during a probe invalidates its result."""
        def changed_target(url: str) -> HealthResult:
            save_environment({'health_check_url': 'https://health.example.com/new'}, self.env)
            return HealthResult(True, 'stale', 5)
        with patch('apps.environments.health.probe_endpoint', side_effect=changed_target):
            self.assertEqual(self.client.post(self.url).status_code, 409)
        self.env.refresh_from_db()
        self.assertEqual(self.env.health_status, 'unknown')
        self.assertIsNone(self.env.health_checked_at)

    def test_newer_probe_result_is_not_overwritten(self) -> None:
        """An older in-flight request cannot overwrite a newer result."""
        def newer_result(url: str) -> HealthResult:
            Environment.objects.filter(pk=self.env.pk).update(health_checked_at=timezone.now(), health_status='unhealthy')
            return HealthResult(True, 'older', 5)
        with patch('apps.environments.health.probe_endpoint', side_effect=newer_result):
            self.assertEqual(self.client.post(self.url).status_code, 409)
        self.env.refresh_from_db()
        self.assertEqual(self.env.health_status, 'unhealthy')

    def test_probe_fields_are_read_only_and_address_change_resets_health(self) -> None:
        """Reject fabricated probe metadata and invalidate old endpoint results."""
        with patch('apps.environments.health.probe_endpoint', return_value=HealthResult(True, 'safe', 1)):
            self.client.post(self.url)
        detail = f'/api/environments/{self.env.pk}/'
        for field, value in (('health_message', 'fake'), ('health_latency_ms', 1), ('health_checked_at', '2026-01-01T00:00:00Z')):
            self.assertEqual(self.client.patch(detail, {field: value}, format='json').status_code, 400)
        response = self.client.patch(detail, {'health_check_url':'https://health.example.com/new'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['health_status'], 'unknown')
        self.assertIsNone(response.data['health_checked_at'])
