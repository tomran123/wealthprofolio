"""Validation for administrator-configured outbound service URLs."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from app.core.config import get_settings

_PROVIDER_HOSTS = {
    "openai": {"api.openai.com"},
    "minimax": {"api.minimax.chat"},
    "deepseek": {"api.deepseek.com"},
    "seed": {"ark.cn-beijing.volces.com"},
}


def validate_llm_base_url(value: str, provider_key: str) -> str:
    settings = get_settings()
    normalized = value.rstrip("/")
    try:
        parsed = urlsplit(normalized)
    except ValueError as exc:
        raise ValueError("invalid_llm_base_url") from exc
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("invalid_llm_base_url")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("invalid_llm_base_url_scheme")
    if settings.environment != "development" and parsed.scheme != "https":
        raise ValueError("llm_base_url_requires_https")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if settings.environment != "development" and address is not None:
        if not address.is_global:
            raise ValueError("llm_base_url_private_address_forbidden")

    configured_hosts = {
        str(host).lower().rstrip(".")
        for host in getattr(settings, "llm_custom_allowed_hosts", [])
        if host
    }
    provider_hosts = _PROVIDER_HOSTS.get(provider_key.lower(), set())
    if (
        settings.environment != "development"
        and hostname not in provider_hosts
        and hostname not in configured_hosts
    ):
        raise ValueError("llm_base_url_host_not_allowed")
    return normalized
