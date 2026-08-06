import unittest

from backend.registration import engine


class ProxyPoolTests(unittest.TestCase):
    def setUp(self):
        self._saved_config = dict(engine.config)
        self._saved_index = engine._proxy_pool_index
        engine.config["proxy"] = "http://127.0.0.1:7890"
        engine.config["proxy_pool"] = ""
        engine.config["proxy_switch_on_failure"] = False
        engine._proxy_pool_index = 0

    def tearDown(self):
        engine.config.clear()
        engine.config.update(self._saved_config)
        engine._proxy_pool_index = self._saved_index

    def _enable_pool(self, entries):
        engine.config["proxy_pool"] = entries
        engine.config["proxy_switch_on_failure"] = True

    def test_parse_pool_supports_newlines_commas_and_comments(self):
        engine.config["proxy_pool"] = (
            "socks5://u1:p1@h1:1001\n"
            "  \n"
            "# 注释行\n"
            "http://h2:1002@u2:p2, socks5://u3:p3@h3:1003 ,\n"
            "\thttp://h4:1004\n"
        )
        self.assertEqual(
            engine.get_proxy_pool(),
            [
                "socks5://u1:p1@h1:1001",
                "http://h2:1002@u2:p2",
                "socks5://u3:p3@h3:1003",
                "http://h4:1004",
            ],
        )

    def test_switch_enabled_requires_flag_and_pool(self):
        self.assertFalse(engine.proxy_pool_switch_enabled())
        engine.config["proxy_switch_on_failure"] = True
        self.assertFalse(engine.proxy_pool_switch_enabled())
        engine.config["proxy_pool"] = "http://h1:1001"
        self.assertTrue(engine.proxy_pool_switch_enabled())

    def test_current_proxy_falls_back_to_single_proxy(self):
        self.assertEqual(engine.get_current_proxy(), "http://127.0.0.1:7890")
        engine.config["proxy_pool"] = "http://h1:1001"
        # 未开启开关时仍然回退单个代理
        self.assertEqual(engine.get_current_proxy(), "http://127.0.0.1:7890")

    def test_current_proxy_uses_pool_when_enabled(self):
        self._enable_pool("http://h1:1001\nhttp://h2:1002")
        self.assertEqual(engine.get_current_proxy(), "http://h1:1001")

    def test_switch_rotates_and_wraps(self):
        self._enable_pool("http://h1:1001\nhttp://h2:1002")
        logs = []
        self.assertEqual(engine.switch_to_next_proxy("失败", logs.append), "http://h2:1002")
        self.assertEqual(engine.get_current_proxy(), "http://h2:1002")
        self.assertEqual(engine.switch_to_next_proxy("失败", logs.append), "http://h1:1001")
        self.assertEqual(engine.get_current_proxy(), "http://h1:1001")
        self.assertEqual(len(logs), 2)
        self.assertIn("2/2", logs[0])
        self.assertIn("1/2", logs[1])

    def test_switch_noop_when_disabled_or_pool_empty(self):
        logs = []
        self.assertEqual(engine.switch_to_next_proxy(log_callback=logs.append), "")
        self._enable_pool("")
        self.assertEqual(engine.switch_to_next_proxy(log_callback=logs.append), "")
        engine.config["proxy_pool"] = "http://h1:1001"
        engine.config["proxy_switch_on_failure"] = False
        self.assertEqual(engine.switch_to_next_proxy(log_callback=logs.append), "")
        self.assertEqual(logs, [])

    def test_get_proxies_uses_current_pool_proxy(self):
        self._enable_pool("http://h1:1001\nhttp://h2:1002")
        proxies = engine.get_proxies()
        self.assertEqual(proxies.get("http"), "http://h1:1001")
        engine.switch_to_next_proxy()
        proxies = engine.get_proxies()
        self.assertEqual(proxies.get("https"), "http://h2:1002")


if __name__ == "__main__":
    unittest.main()
