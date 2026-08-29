from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeOutboundURL(ValueError):
    """Raised when a user-controlled URL targets a private or unsafe address."""


def validate_outbound_url(value: str) -> str:
    """Validate an HTTP(S) URL before making a server-side request.

    DNS is resolved before use and every returned address must be globally
    routable. Callers must disable redirects or validate each redirect target.
    """
    if not isinstance(value, str) or len(value) > 2048:
        raise UnsafeOutboundURL("Invalid outbound URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise UnsafeOutboundURL("Outbound URL must use http or https")
    if parsed.username or parsed.password:
        raise UnsafeOutboundURL("Outbound URL credentials are not allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise UnsafeOutboundURL("Private outbound destinations are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeOutboundURL("Invalid outbound URL port") from exc
    if port is not None and not (1 <= port <= 65535):
        raise UnsafeOutboundURL("Invalid outbound URL port")
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise UnsafeOutboundURL("Unable to resolve outbound host") from exc
    if not addresses:
        raise UnsafeOutboundURL("Unable to resolve outbound host")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeOutboundURL("Private outbound destinations are not allowed")
    return value.strip()
