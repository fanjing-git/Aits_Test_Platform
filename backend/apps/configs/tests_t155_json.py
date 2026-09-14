"""Focused tests for T155 structured response recovery."""

from django.test import SimpleTestCase

from apps.configs.services import ProviderError, _native_message_response, parse_openai_json_response


class T155StructuredResponseTests(SimpleTestCase):
    """Accept safe JSON wrappers without weakening business validation."""

    @staticmethod
    def response(content: object) -> dict[str, object]:
        return {"choices": [{"message": {"content": content}}]}

    def test_thinking_and_markdown_wrappers_are_removed(self) -> None:
        result = parse_openai_json_response(self.response(
            '<think>internal reasoning</think>\nHere is the result:\n```json\n{"ok": true}\n```'
        ))
        self.assertEqual(result, {"ok": True})

    def test_json_object_with_short_suffix_is_recovered(self) -> None:
        result = parse_openai_json_response(self.response('{"ok": true}\nDone.'))
        self.assertEqual(result, {"ok": True})

    def test_non_json_content_still_fails_closed(self) -> None:
        with self.assertRaisesRegex(ProviderError, "不是有效 JSON"):
            parse_openai_json_response(self.response("I cannot return JSON."))

    def test_json_array_is_not_accepted_as_business_object(self) -> None:
        with self.assertRaisesRegex(ProviderError, "JSON 不是对象"):
            parse_openai_json_response(self.response("[1, 2, 3]"))

    def test_length_finish_reason_is_reported_as_truncation(self) -> None:
        response = self.response('{"modules": [')
        response["choices"][0]["finish_reason"] = "length"
        with self.assertRaisesRegex(ProviderError, "达到长度上限"):
            parse_openai_json_response(response)

    def test_native_provider_length_reasons_are_normalized(self) -> None:
        anthropic = _native_message_response("anthropic", {"content": [{"text": '{"ok": true}'}], "stop_reason": "max_tokens"})
        google = _native_message_response("google", {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "MAX_TOKENS"}]})
        for response in (anthropic, google):
            with self.assertRaisesRegex(ProviderError, "达到长度上限"):
                parse_openai_json_response(response)
