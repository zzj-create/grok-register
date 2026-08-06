import unittest
from unittest import mock

from backend.integrations.proxy import parse_proxy_url, redact_proxy_url, resolve_proxy_url


class DockerProxyResolutionTests(unittest.TestCase):
    def test_localhost_proxy_maps_to_docker_host(self):
        with mock.patch.dict(
            "os.environ", {"GROK_DOCKER_PROXY_HOST": "host.docker.internal"}, clear=False
        ):
            self.assertEqual(
                resolve_proxy_url("http://127.0.0.1:7897"),
                "http://host.docker.internal:7897",
            )

    def test_credentials_are_preserved(self):
        with mock.patch.dict(
            "os.environ", {"GROK_DOCKER_PROXY_HOST": "host.docker.internal"}, clear=False
        ):
            self.assertEqual(
                resolve_proxy_url("socks5://user:pass@localhost:7897"),
                "socks5://user:pass@host.docker.internal:7897",
            )

    def test_authenticated_socks5_credentials_are_decoded_for_clients(self):
        parsed = parse_proxy_url("socks5://user%40name:p%40ss@proxy.example:1080")
        self.assertEqual(parsed["scheme"], "socks5")
        self.assertEqual(parsed["hostname"], "proxy.example")
        self.assertEqual(parsed["port"], 1080)
        self.assertEqual(parsed["username"], "user@name")
        self.assertEqual(parsed["password"], "p@ss")

    def test_reverse_http_proxy_credentials_are_normalized(self):
        value = "us.cliproxy.io:3010@user-region-US:password-123"
        parsed = parse_proxy_url(value)
        self.assertTrue(parsed["reverse_auth"])
        self.assertEqual(parsed["scheme"], "http")
        self.assertEqual(parsed["hostname"], "us.cliproxy.io")
        self.assertEqual(parsed["port"], 3010)
        self.assertEqual(parsed["username"], "user-region-US")
        self.assertEqual(parsed["password"], "password-123")
        self.assertEqual(
            resolve_proxy_url(value),
            "http://user-region-US:password-123@us.cliproxy.io:3010",
        )

    def test_reverse_http_proxy_credentials_are_redacted(self):
        self.assertEqual(
            redact_proxy_url("us.cliproxy.io:3010@user:secret"),
            "http://***:***@us.cliproxy.io:3010",
        )

    def test_invalid_proxy_scheme_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_proxy_url("ftp://proxy.example:21")

    def test_invalid_proxy_port_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_proxy_url("socks5://proxy.example:not-a-port")

    def test_proxy_credentials_are_redacted_in_logs(self):
        self.assertEqual(
            redact_proxy_url("socks5://user%40name:p%40ss@proxy.example:1080"),
            "socks5://***:***@proxy.example:1080",
        )

    def test_regular_proxy_is_unchanged(self):
        with mock.patch.dict(
            "os.environ", {"GROK_DOCKER_PROXY_HOST": "host.docker.internal"}, clear=False
        ):
            self.assertEqual(
                resolve_proxy_url("http://proxy.example.com:7897"),
                "http://proxy.example.com:7897",
            )


if __name__ == "__main__":
    unittest.main()
