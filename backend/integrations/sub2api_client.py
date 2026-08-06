# -*- coding: utf-8 -*-
"""面向对象的 Sub2API 管理端客户端。

对接 Wei-Shaw/sub2api 的管理 API，把本地生成的 grok_build OAuth 凭据
（Grok2API JSON 中的 accounts[] 条目）导入为 sub2api 的 grok/oauth 账号：

1. ``POST /api/v1/auth/login``        → JWT（实例内缓存，401 自动重登）
2. ``GET  /api/v1/admin/groups``      → 按名称匹配分组，可自动创建
3. ``GET  /api/v1/admin/accounts``    → 按名称查重（幂等）
4. ``POST /api/v1/admin/accounts``    → 新建 grok oauth 账号
   或 ``PUT /api/v1/admin/accounts/{id}`` → 已存在则刷新凭据

参考 grokcli-2api 的 grok2api/upstream/sub2api_client.py 与 sub2api 源码：
- backend/internal/pkg/response/response.go  → 统一 {code:0, message, data} 包装
- backend/internal/handler/admin/account_handler.go → CreateAccountRequest 结构
- backend/internal/service/grok_oauth_service.go    → grok 凭据字段
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from curl_cffi import requests


class Sub2APIImportError(RuntimeError):
    """远程 Sub2API 登录、分组解析或账号导入失败。"""


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


class Sub2APIClient:
    """封装管理员登录、令牌复用、分组解析与 grok/oauth 账号幂等导入。"""

    LOGIN_PATH = "/api/v1/auth/login"
    GROUPS_PATH = "/api/v1/admin/groups"
    ACCOUNTS_PATH = "/api/v1/admin/accounts"
    CONFIG_KEYS = (
        "sub2api_remote_url",
        "sub2api_remote_email",
        "sub2api_remote_password",
    )
    DEFAULT_GROUP_NAME = "grok-register"
    PLATFORM = "grok"
    ACCOUNT_TYPE = "oauth"
    USER_AGENT = "grok-register-sub2api/1.0"
    _SUCCESS_CODES = (None, 0, "0", 200, "200")

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        *,
        group_id: Any = None,
        group_name: str = "",
        auto_create_group: bool = True,
        account_concurrency: Any = 3,
        account_priority: Any = 50,
        account_rate_multiplier: Any = 1.0,
        session: Any = None,
        login_timeout: float = 20,
        request_timeout: float = 60,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self.email = str(email or "").strip()
        self.password = str(password or "")
        if not self.email or not self.password:
            raise Sub2APIImportError("Sub2API 管理员邮箱或密码为空")
        self.group_id = self._normalize_group_id(group_id)
        self.group_name = str(group_name or "").strip() or self.DEFAULT_GROUP_NAME
        self.auto_create_group = bool(auto_create_group)
        self.account_concurrency = _clamp_int(account_concurrency, 3, 1, 100)
        self.account_priority = _clamp_int(account_priority, 50, 0, 100)
        self.account_rate_multiplier = _clamp_float(account_rate_multiplier, 1.0, 0.1, 10.0)
        self.login_timeout = float(login_timeout)
        self.request_timeout = float(request_timeout)
        self._owns_session = session is None
        # Sub2API 是独立管理服务，不继承项目代理或环境代理。
        self.session = session or requests.Session(trust_env=False)
        self._access_token = ""

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        session: Any = None,
        login_timeout: float = 20,
        request_timeout: float = 60,
    ) -> "Sub2APIClient":
        """从项目配置创建客户端，并统一校验必填字段。"""
        if not cls.is_configured(config):
            raise Sub2APIImportError(
                "请先在系统设置完整配置 Sub2API API 地址、管理员邮箱和密码"
            )
        return cls(
            str(config.get("sub2api_remote_url") or ""),
            str(config.get("sub2api_remote_email") or ""),
            str(config.get("sub2api_remote_password") or ""),
            group_id=config.get("sub2api_group_id"),
            group_name=str(config.get("sub2api_group_name") or ""),
            auto_create_group=bool(config.get("sub2api_auto_create_group", True)),
            account_concurrency=config.get("sub2api_account_concurrency", 3),
            account_priority=config.get("sub2api_account_priority", 50),
            account_rate_multiplier=config.get("sub2api_account_rate_multiplier", 1.0),
            session=session,
            login_timeout=login_timeout,
            request_timeout=request_timeout,
        )

    @classmethod
    def is_configured(cls, config: Mapping[str, Any]) -> bool:
        return all(str(config.get(key, "") or "").strip() for key in cls.CONFIG_KEYS)

    @property
    def access_token(self) -> str:
        """只读暴露当前会话令牌，便于诊断是否已登录。"""
        return self._access_token

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        base = str(value or "").strip().rstrip("/")
        if not base:
            raise Sub2APIImportError("Sub2API API 地址为空")
        if not base.startswith(("http://", "https://")):
            raise Sub2APIImportError(
                "Sub2API API 地址必须以 http:// 或 https:// 开头"
            )
        return base

    @staticmethod
    def _normalize_group_id(value: Any) -> Optional[int]:
        if value in (None, "", 0, "0"):
            return None
        try:
            group_id = int(value)
        except (TypeError, ValueError):
            return None
        return group_id if group_id > 0 else None

    # ------------------------------------------------------------------
    # 响应解析：sub2api 统一 {code, message, data} 包装
    # ------------------------------------------------------------------

    @classmethod
    def _response_error(cls, payload: Any, response: Any, fallback: str) -> str:
        status = int(getattr(response, "status_code", 0) or 0)
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("error") or payload.get("msg")
            if isinstance(message, dict):
                message = message.get("message") or str(message)
            if message:
                return f"HTTP {status}: {message}" if status else str(message)
            code = payload.get("code")
            if code not in cls._SUCCESS_CODES:
                return f"HTTP {status}: code={code}" if status else f"code={code}"
        return f"{fallback} (HTTP {status})" if status else fallback

    @classmethod
    def _unwrap(cls, payload: Any, response: Any, fallback: str) -> Any:
        """校验 HTTP 状态与业务 code，返回 data 字段（无包装则返回整体）。"""
        status = int(getattr(response, "status_code", 0) or 0)
        if status < 200 or status >= 300:
            raise Sub2APIImportError(cls._response_error(payload, response, fallback))
        if isinstance(payload, dict):
            if payload.get("code") not in cls._SUCCESS_CODES:
                raise Sub2APIImportError(cls._response_error(payload, response, fallback))
            if "data" in payload:
                return payload.get("data")
        return payload

    def _authed_request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        retry_login: bool = True,
    ) -> Any:
        token = self.login()
        headers = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
            "Authorization": f"Bearer {token}",
        }
        try:
            response = self.session.request(
                method.upper(),
                f"{self.base_url}{path}",
                json=body,
                params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                headers=headers,
                timeout=timeout or self.request_timeout,
            )
        except Exception as exc:
            raise Sub2APIImportError(f"连接 Sub2API 接口失败: {exc}") from exc
        if (
            int(getattr(response, "status_code", 0) or 0) in (401, 403)
            and retry_login
        ):
            self.login(force=True)
            return self._authed_request(
                method,
                path,
                body=body,
                params=params,
                timeout=timeout,
                retry_login=False,
            )
        try:
            payload = response.json()
        except Exception:
            payload = None
        return payload, response

    # ------------------------------------------------------------------
    # 登录 / 分组
    # ------------------------------------------------------------------

    def login(self, *, force: bool = False) -> str:
        """使用管理员邮箱密码登录；同一实例默认复用已取得的令牌。"""
        if self._access_token and not force:
            return self._access_token
        try:
            response = self.session.post(
                f"{self.base_url}{self.LOGIN_PATH}",
                json={"email": self.email, "password": self.password},
                headers={"Accept": "application/json", "User-Agent": self.USER_AGENT},
                timeout=self.login_timeout,
            )
        except Exception as exc:
            raise Sub2APIImportError(f"连接 Sub2API 登录接口失败: {exc}") from exc
        try:
            payload = response.json()
        except Exception:
            payload = None
        data = self._unwrap(payload, response, "Sub2API 登录失败")
        if not isinstance(data, dict):
            data = payload if isinstance(payload, dict) else {}
        token = str(data.get("access_token") or data.get("token") or "").strip()
        if not token:
            raise Sub2APIImportError("Sub2API 登录响应缺少 access_token")
        self._access_token = token
        return token

    def list_groups(self) -> List[Dict[str, Any]]:
        payload, response = self._authed_request("GET", self.GROUPS_PATH)
        data = self._unwrap(payload, response, "Sub2API 分组列表获取失败")
        items: Any = data
        if isinstance(data, dict):
            items = (
                data.get("items")
                or data.get("groups")
                or data.get("list")
                or []
            )
        if not isinstance(items, list):
            return []
        groups: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            groups.append(
                {
                    "id": item.get("id"),
                    "name": str(item.get("name") or item.get("title") or ""),
                    "platform": str(item.get("platform") or ""),
                }
            )
        return groups

    def create_group(self, name: str) -> Dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise Sub2APIImportError("Sub2API 分组名称为空")
        body = {
            "name": name,
            "platform": self.PLATFORM,
            "description": "created by grok-register",
            "rate_multiplier": 1.0,
            "is_exclusive": False,
        }
        payload, response = self._authed_request("POST", self.GROUPS_PATH, body=body)
        data = self._unwrap(payload, response, "Sub2API 分组创建失败")
        return data if isinstance(data, dict) else {}

    def resolve_group_id(self) -> int:
        """返回配置的分组 ID；否则按名称匹配，找不到时按需自动创建。"""
        if self.group_id:
            return int(self.group_id)
        groups = self.list_groups()
        for group in groups:
            if str(group.get("name") or "").strip().lower() == self.group_name.lower():
                gid = self._normalize_group_id(group.get("id"))
                if gid:
                    self.group_id = gid
                    return gid
        if not self.auto_create_group:
            raise Sub2APIImportError(f"Sub2API 分组不存在: {self.group_name}")
        created = self.create_group(self.group_name)
        gid = self._normalize_group_id(created.get("id"))
        if not gid:
            for group in self.list_groups():
                if str(group.get("name") or "").strip().lower() == self.group_name.lower():
                    gid = self._normalize_group_id(group.get("id"))
                    break
        if not gid:
            raise Sub2APIImportError(f"Sub2API 分组创建失败: {self.group_name}")
        self.group_id = gid
        return gid

    # ------------------------------------------------------------------
    # 账号导入（幂等：按名称查重，存在则刷新凭据）
    # ------------------------------------------------------------------

    def find_account_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        name = str(name or "").strip()
        if not name:
            return None
        payload, response = self._authed_request(
            "GET",
            self.ACCOUNTS_PATH,
            params={"platform": self.PLATFORM, "search": name, "page_size": 50},
        )
        data = self._unwrap(payload, response, "Sub2API 账号查询失败")
        items: Any = data
        if isinstance(data, dict):
            items = data.get("items") or data.get("accounts") or data.get("list") or []
        if not isinstance(items, list):
            return None
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip() == name:
                return item
        return None

    @staticmethod
    def _entry_identity(entry: Mapping[str, Any]) -> tuple[str, str]:
        """返回 (账号名, 邮箱)。"""
        email = str(entry.get("email") or "").strip()
        name = (
            email
            or str(entry.get("user_id") or "").strip()
            or str(entry.get("name") or "").strip()
        )
        return name, email

    def _entry_credentials(self, entry: Mapping[str, Any], email: str) -> Dict[str, Any]:
        access = str(entry.get("access_token") or entry.get("key") or "").strip()
        if not access:
            raise Sub2APIImportError("账号凭据缺少 access_token")
        credentials: Dict[str, Any] = {"access_token": access, "email": email or ""}
        for key in ("refresh_token", "token_type", "id_token", "client_id", "scope"):
            value = str(entry.get(key) or "").strip()
            if value:
                credentials[key] = value
        expires_at = entry.get("expires_at")
        if isinstance(expires_at, str) and expires_at.strip():
            # sub2api 的 BuildAccountCredentials 使用 RFC3339 字符串
            credentials["expires_at"] = expires_at.strip()
        elif isinstance(expires_at, (int, float)) and expires_at > 0:
            import time as _time

            credentials["expires_at"] = _time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", _time.gmtime(float(expires_at))
            )
        return credentials

    def import_account_entry(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        """把一个 grok_build 账号条目导入 sub2api（存在同名账号则刷新凭据）。"""
        if not isinstance(entry, Mapping):
            raise Sub2APIImportError("账号条目格式无效")
        name, email = self._entry_identity(entry)
        if not name:
            raise Sub2APIImportError("账号条目缺少 email/user_id/name")
        credentials = self._entry_credentials(entry, email)
        group_id = self.resolve_group_id()
        notes = f"grok-register:{email or name}"

        existing = self.find_account_by_name(name)
        if existing and self._normalize_group_id(existing.get("id")):
            remote_id = int(existing["id"])
            body = {
                "name": name[:200],
                "type": self.ACCOUNT_TYPE,
                "credentials": credentials,
                "concurrency": self.account_concurrency,
                "priority": self.account_priority,
                "rate_multiplier": self.account_rate_multiplier,
                "notes": notes,
            }
            payload, response = self._authed_request(
                "PUT", f"{self.ACCOUNTS_PATH}/{remote_id}", body=body
            )
            self._unwrap(payload, response, "Sub2API 账号更新失败")
            return {
                "ok": True,
                "action": "updated",
                "name": name,
                "email": email,
                "group_id": group_id,
                "remote_id": remote_id,
            }

        body = {
            "name": name[:200],
            "platform": self.PLATFORM,
            "type": self.ACCOUNT_TYPE,
            "credentials": credentials,
            "extra": {},
            "proxy_id": None,
            "group_ids": [int(group_id)],
            "concurrency": self.account_concurrency,
            "priority": self.account_priority,
            "rate_multiplier": self.account_rate_multiplier,
            "notes": notes,
        }
        payload, response = self._authed_request("POST", self.ACCOUNTS_PATH, body=body)
        data = self._unwrap(payload, response, "Sub2API 账号创建失败")
        remote_id = data.get("id") if isinstance(data, dict) else None
        return {
            "ok": True,
            "action": "created",
            "name": name,
            "email": email,
            "group_id": group_id,
            "remote_id": remote_id,
        }

    @staticmethod
    def load_account_entries(file_path: str | Path) -> List[Dict[str, Any]]:
        """读取 Grok2API grok_build JSON（{"accounts": [...]}）。"""
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise Sub2APIImportError("Grok2API 授权 JSON 文件不存在")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Sub2APIImportError(f"Grok2API 授权 JSON 无效: {exc}") from exc
        entries = document.get("accounts") if isinstance(document, dict) else None
        if isinstance(entries, dict):
            entries = [entries]
        if not entries and isinstance(document, dict) and document.get("access_token"):
            entries = [document]
        if not isinstance(entries, list) or not entries:
            raise Sub2APIImportError("Grok2API 授权 JSON 中没有 accounts 条目")
        return [entry for entry in entries if isinstance(entry, dict)]

    def import_auth_file(self, file_path: str | Path) -> Dict[str, Any]:
        """导入一个 grok_build JSON 文件中的全部账号，返回汇总结果。"""
        entries = self.load_account_entries(file_path)
        results: List[Dict[str, Any]] = []
        created = updated = failed = 0
        for entry in entries:
            try:
                outcome = self.import_account_entry(entry)
            except Sub2APIImportError as exc:
                failed += 1
                name, email = self._entry_identity(entry)
                results.append(
                    {"ok": False, "name": name, "email": email, "error": str(exc)}
                )
                continue
            if outcome.get("action") == "updated":
                updated += 1
            else:
                created += 1
            results.append(outcome)
        return {
            "total": len(entries),
            "created": created,
            "updated": updated,
            "failed": failed,
            "results": results,
        }

    def test_connection(self) -> Dict[str, Any]:
        """登录 + 分组列表冒烟测试，供设置页检测配置。"""
        self.login(force=True)
        groups = self.list_groups()
        return {"ok": True, "message": "连接成功", "groups": groups, "group_count": len(groups)}

    def close(self) -> None:
        """释放客户端自行创建的 HTTP 会话。"""
        if not self._owns_session:
            return
        try:
            self.session.close()
        except Exception:
            pass

    def __enter__(self) -> "Sub2APIClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
