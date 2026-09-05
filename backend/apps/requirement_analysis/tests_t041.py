from unittest.mock import patch
from django.test import SimpleTestCase
from apps.requirement_analysis.adapters import GenericWebAdapter, SwaggerAdapter, adapter_for

class FakeResponse:
    headers = {"Content-Length": "12"}
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, size=-1): return b"hello\r\nworld"

class AdapterTests(SimpleTestCase):
    def test_provider_selection_and_generic_fallback(self):
        self.assertEqual(adapter_for("https://docs.qq.com/sheet/a").source_type, "online_link")
        self.assertEqual(type(adapter_for("https://example.com/spec/openapi.json")), SwaggerAdapter)
        self.assertIsInstance(adapter_for("https://example.com/page"), GenericWebAdapter)
    @patch("apps.requirement_analysis.adapters.urlopen", return_value=FakeResponse())
    def test_fetch_normalizes_text_and_rejects_unsupported_url(self, mocked):
        result = adapter_for("https://example.com/page").fetch("https://example.com/page")
        self.assertEqual(result.content, "hello\nworld"); mocked.assert_called_once()
        with self.assertRaises(ValueError): GenericWebAdapter().fetch("file:///tmp/a")
    def test_swagger_requires_json_content(self):
        with patch("apps.requirement_analysis.adapters.urlopen", return_value=FakeResponse()):
            with self.assertRaises(ValueError): SwaggerAdapter().fetch("https://example.com/openapi.json")
