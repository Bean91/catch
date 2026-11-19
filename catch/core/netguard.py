"""Outbound-URL guards for the two places a user chooses a URL the server will call: a Web Push
endpoint and (personal installs only) an Ollama base URL. Both are server-side request forgery
surfaces — the allowlist/range checks here are the control, not the callers' own validation."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

# The push services the three engines behind every browser's PushManager actually use. A
# subscription endpoint is minted by the browser, never typed by the user, so a closed list costs
# nothing legitimate; anything else is an attacker-chosen URL.
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    ".push.apple.com",
    ".push.services.mozilla.com",
    ".notify.windows.com",
)
MAX_ENDPOINT_CHARS = 1024


class UnsafeUrl(ValueError):
    pass


def is_public_address(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    # `is_global` already excludes private, loopback, link-local (169.254.169.254 included),
    # CGNAT, multicast and reserved space; unwrap IPv4-mapped IPv6 so ::ffff:10.0.0.1 can't slip by.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


def _host_allowed(host: str) -> bool:
    for suffix in PUSH_HOST_SUFFIXES:
        if suffix.startswith("."):
            if host.endswith(suffix) or host == suffix[1:]:
                return True
        elif host == suffix:
            return True
    return False


def validate_push_endpoint(url: str) -> str:
    if not isinstance(url, str) or not url or len(url) > MAX_ENDPOINT_CHARS:
        raise UnsafeUrl("Not a valid push endpoint")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        raise UnsafeUrl("Not a valid push endpoint") from None
    if parts.scheme != "https" or parts.username or parts.password or parts.fragment:
        raise UnsafeUrl("Push endpoints must be plain https URLs")
    if port not in (None, 443):
        raise UnsafeUrl("Push endpoints must use the standard https port")
    if not host or _is_ip_literal(host):
        raise UnsafeUrl("Push endpoints must be a push-service hostname")
    if not _host_allowed(host):
        raise UnsafeUrl("That isn't a recognised browser push service")
    return url


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def resolves_public(host: str, *, resolver=socket.getaddrinfo) -> bool:
    """Defence in depth at send time (the allowlist is the primary control): every address the
    name resolves to must be public. Fails closed when the name doesn't resolve."""
    try:
        infos = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addrs = {info[4][0] for info in infos}
    return bool(addrs) and all(is_public_address(a) for a in addrs)


def validate_outbound_base_url(url: str, *, allow_private: bool) -> str:
    """For a user-supplied model server. A personal install legitimately points this at a LAN or
    localhost Ollama (`allow_private=True`); anything that must not reach internal hosts passes
    False and gets the full range check."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        raise UnsafeUrl("Not a valid URL") from None
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        raise UnsafeUrl("Enter an http(s) URL without credentials")
    if allow_private:
        return url
    if _is_ip_literal(host):
        if not is_public_address(host.strip("[]")):
            raise UnsafeUrl("That address is not reachable from here")
    elif not resolves_public(host):
        raise UnsafeUrl("That host does not resolve to a public address")
    return url
