import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.integrations import sub2api_client
from backend.integrations.sub2api_client import Sub2APIClient, Sub2APIImportError


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, dict(kwargs)))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, dict(kwargs)))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def _config(**overrides):
    base = {
        "sub2api_remote_url": "https://sub2api.test/",
        "sub2api_remote_email": "admin@example.com",
        "sub2api_remote_password": "secret",
    }
    base.update(overrides)
    return base


def _login_response():
    return FakeResponse(
        payload={"code": 0, "message": "success", "data": {"access_token": "jwt-token"}}
    )


def _entry():
    return {
        "provider": "grok_build",
        "name": "user@example.com",
        "client_id": "b1a00492-073a-47ea-816f-4c329264a828",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "token_type": "Bearer",
        "expires_at": "2026-07-10T01:00:00.000000000Z",
        "email": "user@example.com",
        "user_id": "uid-1",
    }


class Sub2APIClientTests(unittest.TestCase):
    def test_owned_session_does_not_inherit_environment_proxy(self):
        session = mock.Mock()
        with mock.patch.object(
            sub2api_client.requests,
            "Session",
            return_value=session,
        ) as factory:
            Sub2APIClient("https://sub2api.test", "admin@example.com", "secret")
        factory.assert_called_once_with(trust_env=False)

    def test_from_config_validates_required_fields(self):
        self.assertTrue(Sub2APIClient.is_configured(_config()))
        self.assertFalse(Sub2APIClient.is_configured(_config(sub2api_remote_url="")))
        self.assertFalse(Sub2APIClient.is_configured(_config(sub2api_remote_email="")))
        with self.assertRaises(Sub2APIImportError):
            Sub2APIClient.from_config(_config(sub2api_remote_password=""))
        with self.assertRaises(Sub2APIImportError):
            Sub2APIClient.from_config(_config(sub2api_remote_url="sub2api.test"))

    def test_login_unwraps_envelope_and_caches_token(self):
        session = FakeSession([_login_response()])
        client = Sub2APIClient(
            "https://sub2api.test/", "admin@example.com", "secret", session=session
        )
        self.assertEqual(client.login(), "jwt-token")
        self.assertEqual(client.login(), "jwt-token")
        self.assertEqual(len(session.calls), 1)
        method, url, kwargs = session.calls[0]
        self.assertEqual(url, "https://sub2api.test/api/v1/auth/login")
        self.assertEqual(kwargs["json"], {"email": "admin@example.com", "password": "secret"})

    def test_login_business_error_raises(self):
        session = FakeSession(
            [FakeResponse(payload={"code": 401, "message": "invalid credentials"})]
        )
        client = Sub2APIClient(
            "https://sub2api.test", "admin@example.com", "bad", session=session
        )
        with self.assertRaisesRegex(Sub2APIImportError, "invalid credentials"):
            client.login()

    def test_import_creates_group_then_account(self):
        session = FakeSession(
            [
                _login_response(),
                FakeResponse(payload={"code": 0, "data": {"items": []}}),  # groups
                FakeResponse(payload={"code": 0, "data": {"id": 7, "name": "grok-register"}}),
                FakeResponse(payload={"code": 0, "data": {"items": []}}),  # account search
                FakeResponse(payload={"code": 0, "data": {"id": 42}}),  # create account
            ]
        )
        client = Sub2APIClient(
            "https://sub2api.test", "admin@example.com", "secret", session=session
        )
        outcome = client.import_account_entry(_entry())
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["action"], "created")
        self.assertEqual(outcome["group_id"], 7)
        self.assertEqual(outcome["remote_id"], 42)

        create_call = session.calls[-1]
        self.assertEqual(create_call[0], "POST")
        self.assertEqual(create_call[1], "https://sub2api.test/api/v1/admin/accounts")
        body = create_call[2]["json"]
        self.assertEqual(body["platform"], "grok")
        self.assertEqual(body["type"], "oauth")
        self.assertEqual(body["group_ids"], [7])
        self.assertEqual(body["concurrency"], 3)
        self.assertEqual(body["priority"], 50)
        self.assertEqual(body["credentials"]["access_token"], "access-token")
        self.assertEqual(body["credentials"]["refresh_token"], "refresh-token")
        self.assertEqual(body["credentials"]["expires_at"], "2026-07-10T01:00:00.000000000Z")
        self.assertEqual(body["credentials"]["email"], "user@example.com")
        self.assertEqual(
            body["credentials"]["client_id"], "b1a00492-073a-47ea-816f-4c329264a828"
        )
        auth_headers = [
            call[2]["headers"].get("Authorization") for call in session.calls[1:]
        ]
        self.assertTrue(all(h == "Bearer jwt-token" for h in auth_headers))

    def test_import_updates_existing_account(self):
        session = FakeSession(
            [
                _login_response(),
                FakeResponse(
                    payload={"code": 0, "data": {"items": [{"id": 7, "name": "grok-register"}]}}
                ),
                FakeResponse(
                    payload={
                        "code": 0,
                        "data": {"items": [{"id": 42, "name": "user@example.com"}]},
                    }
                ),
                FakeResponse(payload={"code": 0, "data": {"id": 42}}),
            ]
        )
        client = Sub2APIClient(
            "https://sub2api.test", "admin@example.com", "secret", session=session
        )
        outcome = client.import_account_entry(_entry())
        self.assertEqual(outcome["action"], "updated")
        self.assertEqual(outcome["remote_id"], 42)
        method, url, kwargs = session.calls[-1]
        self.assertEqual(method, "PUT")
        self.assertEqual(url, "https://sub2api.test/api/v1/admin/accounts/42")
        self.assertEqual(kwargs["json"]["credentials"]["access_token"], "access-token")

    def test_group_resolution_prefers_configured_id(self):
        session = FakeSession(
            [
                _login_response(),
                FakeResponse(payload={"code": 0, "data": {"items": []}}),  # account search
                FakeResponse(payload={"code": 0, "data": {"id": 1}}),
            ]
        )
        client = Sub2APIClient.from_config(
            _config(sub2api_group_id=9), session=session
        )
        outcome = client.import_account_entry(_entry())
        self.assertEqual(outcome["group_id"], 9)
        # 不应请求分组列表
        self.assertFalse(
            any("/admin/groups" in url for _m, url, _k in session.calls)
        )

    def test_auto_create_group_disabled_raises(self):
        session = FakeSession(
            [
                _login_response(),
                FakeResponse(payload={"code": 0, "data": {"items": []}}),
            ]
        )
        client = Sub2APIClient.from_config(
            _config(sub2api_auto_create_group=False), session=session
        )
        with self.assertRaisesRegex(Sub2APIImportError, "分组不存在"):
            client.import_account_entry(_entry())

    def test_import_auth_file_aggregates_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g2a-user.json"
            path.write_text(
                json.dumps({"accounts": [_entry(), {"email": "broken@example.com"}]}),
                encoding="utf-8",
            )
            session = FakeSession(
                [
                    _login_response(),
                    FakeResponse(
                        payload={
                            "code": 0,
                            "data": {"items": [{"id": 7, "name": "grok-register"}]},
                        }
                    ),
                    FakeResponse(payload={"code": 0, "data": {"items": []}}),
                    FakeResponse(payload={"code": 0, "data": {"id": 42}}),
                ]
            )
            client = Sub2APIClient(
                "https://sub2api.test", "admin@example.com", "secret", session=session
            )
            summary = client.import_auth_file(path)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(len(summary["results"]), 2)

    def test_import_auth_file_rejects_invalid_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
            client = Sub2APIClient(
                "https://sub2api.test", "admin@example.com", "secret", session=FakeSession([])
            )
            with self.assertRaisesRegex(Sub2APIImportError, "accounts"):
                client.import_auth_file(path)

    def test_401_triggers_relogin_once(self):
        session = FakeSession(
            [
                _login_response(),
                FakeResponse(status=401, payload={"code": 401, "message": "expired"}),
                _login_response(),
                FakeResponse(
                    payload={"code": 0, "data": {"items": [{"id": 7, "name": "grok-register"}]}}
                ),
            ]
        )
        client = Sub2APIClient(
            "https://sub2api.test", "admin@example.com", "secret", session=session
        )
        groups = client.list_groups()
        self.assertEqual(groups[0]["id"], 7)
        logins = [c for c in session.calls if c[1].endswith("/auth/login")]
        self.assertEqual(len(logins), 2)


if __name__ == "__main__":
    unittest.main()
