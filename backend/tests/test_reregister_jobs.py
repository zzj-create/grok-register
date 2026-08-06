import os
import tempfile
import time
import types
import unittest
from unittest import mock

from backend.registration import engine
from backend.registration.store import RegistrationRepository
from backend.web.reregister_jobs import ReregisterJobCoordinator


def _failed_record(repo, email="fail@example.com"):
    return repo.add_result(
        {
            "email": email,
            "status": "failure",
            "failure_reason": "code timeout",
            "provider": "outlookemail",
        }
    )


class ReregisterValidationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = RegistrationRepository(os.path.join(self._tmp.name, "t.db"))
        self._repo_patch = mock.patch.object(
            engine, "get_registration_repository", return_value=self.repo
        )
        self._repo_patch.start()
        self.coordinator = ReregisterJobCoordinator()

    def tearDown(self):
        self._repo_patch.stop()
        self._tmp.cleanup()

    def test_empty_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "请选择要重新注册的账号"):
            self.coordinator.start_many([])

    def test_missing_record_raises_lookup(self):
        with self.assertRaises(LookupError):
            self.coordinator.start_many([999999])

    def test_success_records_are_not_runnable(self):
        rid = self.repo.add_result(
            {"email": "ok@example.com", "status": "success", "provider": "outlookemail"}
        )
        with self.assertRaisesRegex(ValueError, "已注册成功"):
            self.coordinator.start_many([rid])

    def test_failed_record_runs_and_completes(self):
        rid = _failed_record(self.repo)
        self.coordinator._run_record = lambda record, store: ""
        status = self.coordinator.start(rid)
        # mock 立即返回时线程可能在 status() 调用前就已结束，两种状态都接受
        self.assertIn(status["running"], (True, False))
        self.coordinator._thread.join(timeout=10)
        final = self.coordinator.status()
        self.assertFalse(final["running"])
        self.assertEqual(final["success_count"], 1)
        self.assertEqual(final["failed_count"], 0)
        self.assertEqual(final["stage"], "重新注册完成")

    def test_failed_record_error_counts_as_failed(self):
        rid = _failed_record(self.repo)
        self.coordinator._run_record = lambda record, store: "boom"
        self.coordinator.start(rid)
        self.coordinator._thread.join(timeout=10)
        final = self.coordinator.status()
        self.assertEqual(final["failed_count"], 1)
        self.assertEqual(final["error"], "boom")

    def test_concurrent_start_rejected(self):
        rid = _failed_record(self.repo)
        gate = []

        def slow_run(record, store):
            gate.append(record["id"])
            time.sleep(0.3)
            return ""

        self.coordinator._run_record = slow_run
        self.coordinator.start(rid)
        with self.assertRaisesRegex(RuntimeError, "正在重新注册"):
            self.coordinator.start(rid)
        self.coordinator._thread.join(timeout=10)


class ReregisterResultMappingTests(unittest.TestCase):
    def test_build_result_record_maps_all_fields(self):
        coordinator = ReregisterJobCoordinator()
        gr = types.SimpleNamespace(
            config={"email_provider": "outlookemail", "cpa_auto_add": True},
            default_email_disable_detail=lambda provider="", detail=None: {
                "status": "not_attempted",
                "account_id": "",
                "disabled_at": "",
                "error": "",
            },
        )
        record = coordinator._build_result_record(
            gr=gr,
            batch_id="reregister-x",
            attempt_started_at=time.time() - 5,
            email="user@example.com",
            profile={"password": "pw"},
            status="success",
            cpa_detail={
                "enabled": True,
                "status": "success",
                "auth_info": ["CPA 本地: /a.json", "Sub2API 远程: https://s2"],
                "auth_path": "/a.json",
                "cpa_remote_status": "success",
                "grok2api_remote_status": "failed",
                "grok2api_remote_error": "boom",
                "sub2api_remote_status": "success",
                "sub2api_remote_imported_at": "2026-08-07 12:00:00",
                "mode": "device_protocol",
            },
            email_disable_detail={"status": "success", "account_id": "42"},
            account_file="/data/accounts/user@example.com.txt",
            sso_saved=True,
            nsfw_status="成功",
        )
        self.assertEqual(record["source"], "reregister")
        self.assertEqual(record["batch_id"], "reregister-x")
        self.assertTrue(record["success"])
        self.assertEqual(record["cpa_status"], "success")
        self.assertEqual(record["auth_info"], "CPA 本地: /a.json\nSub2API 远程: https://s2")
        self.assertEqual(record["sub2api_remote_status"], "success")
        self.assertEqual(record["grok2api_remote_status"], "failed")
        self.assertEqual(record["email_disable_status"], "success")
        self.assertEqual(record["email_account_id"], "42")
        self.assertEqual(record["extra"]["cpa_mode"], "device_protocol")
        self.assertGreaterEqual(record["duration_seconds"], 4)


if __name__ == "__main__":
    unittest.main()
