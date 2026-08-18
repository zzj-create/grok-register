"""邮箱渠道共享的小型解析工具。"""

from __future__ import annotations

import re
import secrets
import string
from typing import Any, List, Optional


def generate_username(length: int = 10) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(max(3, length)))


def pick_list_payload(data: Any) -> List[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            return [item for item in data["results"] if isinstance(item, dict)]
        if isinstance(data.get("hydra:member"), list):
            return [item for item in data["hydra:member"] if isinstance(item, dict)]
        if isinstance(data.get("data"), list):
            return [item for item in data["data"] if isinstance(item, dict)]
        if isinstance(data.get("messages"), list):
            return [item for item in data["messages"] if isinstance(item, dict)]
        if isinstance(data.get("data"), dict):
            nested = data.get("data") or {}
            if isinstance(nested.get("messages"), list):
                return [item for item in nested["messages"] if isinstance(item, dict)]
    return []


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# 验证码形如 I6R-B2W：必须全大写，否则邮件模板里的 CSS 类名（如 sm-w-per-100）会被误判。
_CODE_TOKEN = r"[A-Z0-9]{3}-[A-Z0-9]{3}"
_CODE_WITH_CONTEXT_RE = re.compile(
    r"(?:code|验证码)\s*(?:is|：|:)?\s*\b(" + _CODE_TOKEN + r")\b", re.IGNORECASE
)
_CODE_BARE_RE = re.compile(r"\b(" + _CODE_TOKEN + r")\b")
_NUMERIC_CODE_RES = [
    re.compile(r"verification\s+code[:\s]+(\d{4,8})", re.IGNORECASE),
    re.compile(r"your\s+code[:\s]+(\d{4,8})", re.IGNORECASE),
    re.compile(r"confirm(?:ation)?\s+code[:\s]+(\d{4,8})", re.IGNORECASE),
]


def strip_html(html: str) -> str:
    """剥掉 HTML 标签，取纯文本。

    必须先删除 script/style 块与注释：只删尖括号的话，<style> 里的 CSS 正文
    会原样留在结果里，其中的类名（如 .sm-w-per-100）会被验证码正则误命中。
    """
    if not html:
        return ""
    cleaned = _SCRIPT_STYLE_RE.sub(" ", html)
    cleaned = _COMMENT_RE.sub(" ", cleaned)
    return _TAG_RE.sub(" ", cleaned)


def _match_code(pattern: re.Pattern, source: str, *, require_alpha: bool = True) -> Optional[str]:
    """取第一个匹配。

    require_alpha=True 时只接受含字母的 token，避免 CSS 类名、编号（如
    100-200）被误判；带 code/验证码 上下文锚定的匹配可以放心接受纯数字
    （xAI 会发 393-696 这类纯数字验证码）。
    """
    for match in pattern.finditer(source):
        token = match.group(1)
        if not require_alpha or any(ch.isalpha() for ch in token):
            return token
    return None


def extract_verification_code(text: str, subject: str = "") -> Optional[str]:
    subject = subject or ""
    text = text or ""
    # 主题最干净，优先；正文里带 code 关键字的上下文次之，裸 token 最后。
    # 上下文已锚定 code/验证码，允许纯数字 token；裸 token 仍然必须含字母。
    for source in (subject, text):
        code = _match_code(_CODE_WITH_CONTEXT_RE, source, require_alpha=False)
        if code:
            return code
    for source in (subject, text):
        code = _match_code(_CODE_BARE_RE, source, require_alpha=True)
        if code:
            return code
    for pattern in _NUMERIC_CODE_RES:
        match = pattern.search(text) or pattern.search(subject)
        if match:
            return match.group(1)
    return None
