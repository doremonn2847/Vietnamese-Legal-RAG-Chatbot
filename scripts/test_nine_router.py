import unittest

from nine_router import NineRouterConfig, NineRouterProvider


class NineRouterTest(unittest.TestCase):
    def test_disabled_and_mocked_transport(self):
        provider = NineRouterProvider(NineRouterConfig(), transport=lambda *args: (_ for _ in ()).throw(AssertionError("must not call")))
        with self.assertRaises(RuntimeError):
            provider.generate([])
        calls = []
        provider = NineRouterProvider(NineRouterConfig(base_url="https://example.invalid", route="chat", model="free-test", enabled=True), transport=lambda *args: calls.append(args) or {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 1}}, api_key="not-logged")
        self.assertEqual(provider.generate([])["usage"]["total_tokens"], 1)
        self.assertEqual(calls[0][1], "https://example.invalid/chat")


if __name__ == "__main__":
    unittest.main()
