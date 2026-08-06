"""代理地址归一化。

容器运行时将指向本机回环地址的代理主机映射为 Docker Host 别名，同时保留认证
信息、端口和 URL 其他组成部分。
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit, urlunsplit


LOCAL_PROXY_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks4", "socks5"}


def _normalize_reverse_auth(value: str) -> tuple[str, bool]:
    """Normalize ``host:port@username:password`` proxy credentials.

    Some proxy providers publish HTTP endpoints with the host/port before the
    credentials (for example ``us.cliproxy.io:3010@user:pass``).  That is not
    a URI authority accepted by urllib/curl, so turn it into the canonical
    ``http://user:pass@us.cliproxy.io:3010`` form before parsing.  A scheme URL
    is never rewritten, because an ``@`` in its authority has the standard
    username/password meaning already.
    """
    raw = str(value or "").strip()
    if not raw or "@" not in raw:
        return raw, False

    # With an explicit scheme, ``user:password@host:port`` and the reverse
    # spelling are syntactically ambiguous.  Keep standard URI semantics and
    # accept the provider-specific reverse form only when it is scheme-less.
    if "://" in raw:
        return raw, False
    scheme = "http"
    authority = raw

    endpoint, credentials = authority.rsplit("@", 1)
    # The left side must be a host and numeric port.  Requiring exactly one
    # colon keeps IPv6 and malformed values on the normal validation path.
    if endpoint.count(":") != 1 or not credentials:
        return raw, False
    host, port = endpoint.rsplit(":", 1)
    if not host or not port.isdigit():
        return raw, False
    if ":" not in credentials:
        return raw, False
    username, password = credentials.split(":", 1)
    if not username or not password:
        return raw, False
    return f"{scheme}://{username}:{password}@{host}:{port}", True


def normalize_proxy_url(proxy_url: str) -> str:
    """Return a canonical URL for either supported credential ordering."""
    value = str(proxy_url or "").strip()
    if not value:
        return value
    normalized, _ = _normalize_reverse_auth(value)
    return normalized


def parse_proxy_url(proxy_url: str) -> dict:
    """Parse a proxy URL into client-neutral components.

    The web setting accepts normal proxy URLs, including authenticated SOCKS5
    URLs such as ``socks5://username:password@host:port``.  Credentials are
    URL-decoded only for clients (for example Playwright) that receive them as
    separate fields; callers that pass the URL directly to libcurl should keep
    the original URL so its escaping is preserved.
    """
    value = str(proxy_url or "").strip()
    if not value:
        return {}

    value, reverse_auth = _normalize_reverse_auth(value)
    has_scheme = "://" in value
    parsed = urlsplit(value if has_scheme else f"http://{value}")
    scheme = str(parsed.scheme or "").lower()
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("代理端口必须是 1-65535 的数字") from exc

    if has_scheme and scheme not in SUPPORTED_PROXY_SCHEMES:
        raise ValueError(
            f"不支持的代理协议 {scheme!r}，请使用 http、https、socks4 或 socks5"
        )
    if not hostname:
        raise ValueError("代理地址缺少主机名")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("代理端口必须是 1-65535 的数字")

    return {
        "value": value,
        "has_scheme": has_scheme,
        "reverse_auth": reverse_auth,
        "scheme": scheme or "http",
        "hostname": hostname,
        "port": port,
        "username": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
    }


def redact_proxy_url(proxy_url: str) -> str:
    """Return a log-safe proxy URL without exposing username/password."""
    value = str(proxy_url or "").strip()
    if not value or "@" not in value:
        return value
    try:
        parsed = parse_proxy_url(value)
    except ValueError:
        return "<proxy credentials hidden>"
    host = parsed["hostname"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    authority = host
    if parsed["port"] is not None:
        authority += f":{parsed['port']}"
    if parsed["has_scheme"]:
        return f"{parsed['scheme']}://***:***@{authority}"
    return f"***:***@{authority}"


def resolve_proxy_url(proxy_url: str) -> str:
    """Replace a local proxy host with the Docker host alias when configured."""
    value = str(proxy_url or "").strip()
    if not value:
        return value

    parsed_info = parse_proxy_url(value)
    normalized = parsed_info.get("value", value)
    docker_host = str(os.environ.get("GROK_DOCKER_PROXY_HOST", "") or "").strip()
    if not docker_host:
        return normalized if parsed_info.get("reverse_auth") else value

    parsed = urlsplit(normalized if parsed_info["has_scheme"] else f"http://{normalized}")
    if parsed_info["hostname"].lower() not in LOCAL_PROXY_HOSTS:
        # Reverse-auth input is normalized even when no Docker host mapping is
        # configured; curl/urllib need a canonical URI rather than the
        # provider's ``host:port@user:pass`` display form.
        return normalized if parsed_info.get("reverse_auth") else value

    auth = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    port = f":{parsed.port}" if parsed.port else ""
    resolved = urlunsplit(
        (parsed.scheme, f"{auth}{docker_host}{port}", parsed.path, parsed.query, parsed.fragment)
    )
    if parsed_info.get("reverse_auth"):
        return resolved
    return resolved if parsed_info["has_scheme"] else resolved.split("://", 1)[1]
