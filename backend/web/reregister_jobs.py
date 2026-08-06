# -*- coding: utf-8 -*-
"""失败账号重新注册后台任务。

针对注册失败（success=0）的记录，复用 ``backend.registration`` 的完整注册流程
重跑一次：打开注册页 → 邮箱提交 → 验证码 → 资料 → SSO → 授权入库。

邮箱策略：
- outlookemail / mailnest 提供商取验证码只依赖邮箱本身，支持**同邮箱重新注册**；
- 其他提供商的邮箱 token 无法从历史记录恢复，自动**更换新邮箱**重新注册。

每条记录处理完毕后结果直接覆盖原失败记录（保留 id 与 source_key）。
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# 取验证码不需要 dev_token 的提供商，允许同邮箱重新注册
SAME_EMAIL_PROVIDERS = {"outlookemail", "mailnest"}


class ReregisterJobCoordinator:
    """Single-flight re-registration runner for failed records."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running = False
        self._stop_requested = False
        self._account_id = 0
        self._email = ""
        self._stage = "等待启动"
        self._error = ""
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None
        self._total_count = 0
        self._completed_count = 0
        self._success_count = 0
        self._failed_count = 0
        self._thread: Optional[threading.Thread] = None

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "account_id": self._account_id,
                "email": self._email,
                "stage": self._stage,
                "error": self._error,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "total_count": self._total_count,
                "completed_count": self._completed_count,
                "success_count": self._success_count,
                "failed_count": self._failed_count,
            }

    def _set(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self, f"_{key}", value)

    def request_stop(self) -> Dict[str, Any]:
        with self._lock:
            self._stop_requested = True
            running = self._running
        if running:
            self._set(stage="正在停止…")
        return self.status()

    def start(self, account_id: int) -> Dict[str, Any]:
        return self.start_many([account_id])

    def start_many(self, account_ids: Iterable[int]) -> Dict[str, Any]:
        from backend.registration import engine as gr

        normalized_ids: List[int] = []
        seen = set()
        for raw_id in account_ids or []:
            try:
                account_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if account_id <= 0 or account_id in seen:
                continue
            seen.add(account_id)
            normalized_ids.append(account_id)
        if not normalized_ids:
            raise ValueError("请选择要重新注册的账号")
        with self._lock:
            if self._running:
                raise RuntimeError(f"账号 {self._email or self._account_id} 正在重新注册")

        store = gr.get_registration_repository()
        records = store.get_results_by_ids(normalized_ids)
        if not records:
            message = "记录不存在" if len(normalized_ids) == 1 else "没有匹配的记录"
            raise LookupError(message)
        records_by_id = {int(record.get("id") or 0): record for record in records}

        runnable: List[Dict[str, Any]] = []
        validation_errors: List[str] = []
        for account_id in normalized_ids:
            record = records_by_id.get(account_id)
            if record is None:
                validation_errors.append(f"账号 {account_id}: 记录不存在")
                continue
            label = str(record.get("email") or "").strip() or f"账号 {account_id}"
            if int(record.get("success") or 0) == 1 or str(record.get("status") or "") == "success":
                validation_errors.append(f"{label}: 已注册成功，无需重新注册")
                continue
            runnable.append(record)
        if not runnable:
            raise ValueError(f"所选账号均无法重新注册：{validation_errors[0]}")

        with self._lock:
            if self._running:
                raise RuntimeError(f"账号 {self._email or self._account_id} 正在重新注册")
            first = runnable[0]
            self._running = True
            self._stop_requested = False
            self._account_id = int(first.get("id") or 0)
            self._email = str(first.get("email") or "").strip()
            self._stage = "启动浏览器"
            self._error = ""
            self._started_at = time.time()
            self._finished_at = None
            self._total_count = len(normalized_ids)
            self._completed_count = len(validation_errors)
            self._success_count = 0
            self._failed_count = len(validation_errors)

        def runner() -> None:
            errors = list(validation_errors)
            try:
                for record in runnable:
                    if self._stop_requested:
                        errors.append("用户停止重新注册")
                        with self._lock:
                            self._failed_count += self._total_count - self._completed_count
                            self._completed_count = self._total_count
                        break
                    error = ""
                    try:
                        self._set(
                            account_id=int(record.get("id") or 0),
                            email=str(record.get("email") or "").strip(),
                            stage="打开注册页",
                        )
                        error = self._run_record(record, store)
                    except Exception as exc:
                        error = str(exc) or exc.__class__.__name__
                    if error:
                        errors.append(f"{record.get('email') or record.get('id')}: {error}")
                    with self._lock:
                        self._completed_count += 1
                        if error:
                            self._failed_count += 1
                        else:
                            self._success_count += 1
            finally:
                with self._lock:
                    if self._total_count == 1:
                        self._stage = "重新注册失败" if errors else "重新注册完成"
                        self._error = errors[0].split(": ", 1)[-1] if errors else ""
                    else:
                        self._stage = (
                            f"批量重新注册完成（成功 {self._success_count}，失败 {self._failed_count}）"
                        )
                        self._error = f"{self._failed_count} 个账号重新注册失败" if errors else ""
                    self._running = False
                    self._stop_requested = False
                    self._finished_at = time.time()

        self._thread = threading.Thread(
            target=runner,
            name=f"account-reregister-{self._account_id}",
            daemon=True,
        )
        try:
            self._thread.start()
        except Exception as exc:
            self._set(running=False, error=str(exc), finished_at=time.time())
            raise
        return self.status()

    # ------------------------------------------------------------------

    def _build_result_record(
        self,
        *,
        gr: Any,
        batch_id: str,
        attempt_started_at: float,
        email: str,
        profile: Dict[str, Any],
        status: str,
        cpa_detail: Dict[str, Any],
        email_disable_detail: Dict[str, Any],
        failure_type: str = "",
        failure_reason: str = "",
        account_file: str = "",
        sso_saved: bool = False,
        nsfw_status: str = "",
        screenshot_path: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """把一次重新注册尝试映射为 registration_results 记录（对齐 persist_registration_result）。"""
        detail = dict(cpa_detail or {})
        provider_name = str(gr.config.get("email_provider", "") or "")
        cpa_enabled = bool(detail.get("enabled", gr.config.get("cpa_auto_add", False)))
        cpa_status = str(
            detail.get("status")
            or ("disabled" if not cpa_enabled else "not_attempted")
        )
        auth_info = detail.get("auth_info", "")
        if isinstance(auth_info, (list, tuple, set)):
            auth_info = "\n".join(str(item) for item in auth_info if str(item).strip())
        extra_data = dict(extra or {})
        if detail.get("error"):
            extra_data["cpa_error"] = str(detail.get("error"))
        if detail.get("mode"):
            extra_data["cpa_mode"] = str(detail.get("mode"))
        disable_detail = gr.default_email_disable_detail(provider_name, detail)
        disable_detail.update(dict(email_disable_detail or {}))
        finished_epoch = time.time()
        return {
            "batch_id": batch_id,
            "source": "reregister",
            "started_at": _fmt_ts(attempt_started_at),
            "finished_at": _fmt_ts(finished_epoch),
            "duration_seconds": max(finished_epoch - attempt_started_at, 0),
            "email": email,
            "password": str(profile.get("password") or ""),
            "status": status,
            "success": status == "success",
            "provider": provider_name,
            "worker_id": 0,
            "cpa_enabled": cpa_enabled,
            "cpa_status": cpa_status,
            "auth_info": auth_info,
            "auth_path": detail.get("auth_path", ""),
            "cpa_auth_path": detail.get("cpa_auth_path", ""),
            "grok2api_auth_path": detail.get("grok2api_auth_path", ""),
            "cpa_remote_status": detail.get("cpa_remote_status", "not_configured"),
            "cpa_remote_imported_at": detail.get("cpa_remote_imported_at", ""),
            "cpa_remote_error": detail.get("cpa_remote_error", ""),
            "grok2api_remote_status": detail.get("grok2api_remote_status", "not_configured"),
            "grok2api_remote_imported_at": detail.get("grok2api_remote_imported_at", ""),
            "grok2api_remote_error": detail.get("grok2api_remote_error", ""),
            "sub2api_remote_status": detail.get("sub2api_remote_status", "not_configured"),
            "sub2api_remote_imported_at": detail.get("sub2api_remote_imported_at", ""),
            "sub2api_remote_error": detail.get("sub2api_remote_error", ""),
            "email_account_id": disable_detail.get("account_id", ""),
            "email_disable_status": disable_detail.get("status", "not_attempted"),
            "email_disabled_at": disable_detail.get("disabled_at", ""),
            "email_disable_error": disable_detail.get("error", ""),
            "failure_type": failure_type,
            "failure_reason": failure_reason,
            "screenshot_path": screenshot_path,
            "account_file": account_file,
            "sso_saved": sso_saved,
            "nsfw_status": nsfw_status,
            "extra": extra_data,
        }

    def _run_record(self, record: Dict[str, Any], store: Any) -> str:
        """对单条失败记录重跑完整注册流程；返回空串表示成功，否则为错误信息。"""
        from backend.automation.session import stop_browser
        from backend.registration import engine as gr
        from backend.registration import signup_flow as _rf
        from backend.registration.signup_flow import AccountAlreadyRegistered

        account_id = int(record.get("id") or 0)
        old_email = str(record.get("email") or "").strip()
        provider = ""
        same_email = False
        batch_id = f"reregister-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        attempt_started_at = time.time()
        email = ""
        profile: Dict[str, Any] = {}
        sso = ""
        email_file = ""
        screenshot_path = ""
        nsfw_status = "未执行"
        cpa_detail: Dict[str, Any] = {}

        def log(message: str) -> None:
            text = str(message or "")
            if "打开注册页" in text:
                self._set(stage="打开注册页")
            elif "创建邮箱并提交" in text or "已创建邮箱" in text:
                self._set(stage="创建并提交邮箱")
            elif "拉取验证码" in text:
                self._set(stage="等待邮箱验证码")
            elif "填写资料" in text:
                self._set(stage="填写账号资料")
            elif "等待 sso" in text:
                self._set(stage="等待登录凭证")
            elif "开启 NSFW" in text:
                self._set(stage="更新账号设置")
            elif "[CPA]" in text:
                self._set(stage="转换并写入授权")

        def should_stop() -> bool:
            return bool(self._stop_requested)

        try:
            gr.load_config()
            gr._wire_runtime_modules()
            gr._bs.allow_browser_launches()
            provider = str(gr.get_email_provider() or "").strip().lower()
            same_email = provider in SAME_EMAIL_PROVIDERS and "@" in old_email
            if same_email:
                log(f"[*] 同邮箱重新注册: {old_email}")
                _rf.configure(get_email_and_token=lambda *a, **k: (old_email, "_"))

            cpa_detail = {
                "enabled": bool(gr.config.get("cpa_auto_add", False)),
                "status": "not_attempted" if gr.config.get("cpa_auto_add") else "disabled",
            }

            self._set(stage="打开注册页")
            gr.open_signup_page(log_callback=log, cancel_callback=should_stop)
            self._set(stage="创建并提交邮箱")
            email, dev_token, submitted_at = gr.fill_email_and_submit(
                log_callback=log, cancel_callback=should_stop
            )
            log(f"[*] 邮箱: {email}")
            self._set(stage="等待邮箱验证码")
            code = gr.fill_code_and_submit(
                email,
                dev_token,
                submitted_at=submitted_at,
                log_callback=log,
                cancel_callback=should_stop,
            )
            log(f"[*] 验证码: {code}")
            self._set(stage="填写账号资料")
            profile = gr.fill_profile_and_submit(
                log_callback=log, cancel_callback=should_stop
            )
            self._set(stage="等待登录凭证")
            sso = gr.wait_for_sso_cookie(log_callback=log, cancel_callback=should_stop)
            gr.ensure_sso_oauth_eligible(sso, email=email, log_callback=log)
            if gr.config.get("enable_nsfw", True):
                self._set(stage="更新账号设置")
                nsfw_ok, nsfw_msg = gr.enable_nsfw_for_token(sso, log_callback=log)
                nsfw_status = "成功" if nsfw_ok else f"失败: {nsfw_msg}"
            else:
                nsfw_status = "未开启"

            self._set(stage="保存账号文件")
            line = f"{email}----{profile.get('password','')}----{sso}\n"
            email_file = gr.account_file_for_email(email)
            Path(email_file).parent.mkdir(parents=True, exist_ok=True)
            with open(email_file, "w", encoding="utf-8") as handle:
                handle.write(line)

            self._set(stage="转换并写入授权")
            gr.add_sso_to_cpa(sso, email=email, log_callback=log, result_out=cpa_detail)
            if not gr.registration_counts_as_success(cpa_detail):
                reason = gr.cpa_failure_reason(cpa_detail)
                store.update_reregister_result(
                    account_id,
                    self._build_result_record(
                        gr=gr,
                        batch_id=batch_id,
                        attempt_started_at=attempt_started_at,
                        email=email,
                        profile=profile,
                        status="failure",
                        cpa_detail=cpa_detail,
                        email_disable_detail=gr.default_email_disable_detail("", cpa_detail),
                        failure_type=gr.FAIL_CPA,
                        failure_reason=reason,
                        account_file=email_file,
                        sso_saved=True,
                        nsfw_status=nsfw_status,
                    ),
                )
                return f"授权转换失败: {reason}"

            email_disable_detail = (
                gr.disable_outlookemail_after_cpa_success(
                    email, cpa_detail, log_callback=log
                )
                if gr.is_outlookemail_registration()
                else gr.default_email_disable_detail("", cpa_detail)
            )
            store.update_reregister_result(
                account_id,
                self._build_result_record(
                    gr=gr,
                    batch_id=batch_id,
                    attempt_started_at=attempt_started_at,
                    email=email,
                    profile=profile,
                    status="success",
                    cpa_detail=cpa_detail,
                    email_disable_detail=email_disable_detail,
                    account_file=email_file,
                    sso_saved=True,
                    nsfw_status=nsfw_status,
                ),
            )
            return ""
        except gr.RegistrationCancelled:
            store.update_reregister_result(
                account_id,
                self._build_result_record(
                    gr=gr,
                    batch_id=batch_id,
                    attempt_started_at=attempt_started_at,
                    email=email or old_email,
                    profile=profile,
                    status="cancelled",
                    cpa_detail=cpa_detail,
                    email_disable_detail={},
                    failure_reason="用户停止重新注册",
                    account_file=email_file,
                    sso_saved=bool(email_file),
                    nsfw_status=nsfw_status,
                ),
            )
            return "用户停止重新注册"
        except AccountAlreadyRegistered as exc:
            reason = f"该邮箱已注册，请改用重新登录刷新授权: {exc}"
            store.update_reregister_result(
                account_id,
                self._build_result_record(
                    gr=gr,
                    batch_id=batch_id,
                    attempt_started_at=attempt_started_at,
                    email=email or old_email,
                    profile=profile,
                    status="failure",
                    cpa_detail=cpa_detail,
                    email_disable_detail={},
                    failure_type="duplicate",
                    failure_reason=reason,
                    account_file=email_file,
                    sso_saved=bool(email_file),
                    nsfw_status=nsfw_status,
                ),
            )
            return reason
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            try:
                kind = gr.classify_failure(exc)
            except Exception:
                kind = "other"
            if kind == gr.FAIL_RISK:
                cpa_detail.update(status="rejected", error=error)
            try:
                screenshot_path = gr.capture_failure_screenshot(
                    batch_id=batch_id,
                    worker_id=0,
                    email=email or old_email,
                    failure_type=kind,
                    log_callback=log,
                )
            except Exception:
                screenshot_path = ""
            store.update_reregister_result(
                account_id,
                self._build_result_record(
                    gr=gr,
                    batch_id=batch_id,
                    attempt_started_at=attempt_started_at,
                    email=email or old_email,
                    profile=profile,
                    status="failure",
                    cpa_detail=cpa_detail,
                    email_disable_detail={},
                    failure_type=kind,
                    failure_reason=error,
                    account_file=email_file,
                    sso_saved=bool(email_file) or bool(sso and kind == gr.FAIL_RISK),
                    nsfw_status=nsfw_status,
                    screenshot_path=screenshot_path,
                ),
            )
            return error
        finally:
            try:
                # 恢复默认的邮箱生成注入，避免影响后续注册任务
                gr._wire_runtime_modules()
            except Exception:
                pass
            try:
                stop_browser(force=True)
            except BaseException:
                pass


def _fmt_ts(epoch: float) -> str:
    import datetime

    return (
        datetime.datetime.fromtimestamp(epoch)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S")
    )


reregister_coordinator = ReregisterJobCoordinator()
