"""URL validation and SSRF protection (syntax checks + resolved-IP checks)."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import SplitResult, urlsplit

from core.errors import BlockedHost, InvalidURL

MAX_URL_LENGTH = 2048
BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".intranet", ".corp")
BLOCKED_NAMES = {"localhost", "metadata", "metadata.google.internal"}

Resolver = Callable[[str, int], Awaitable[list[str]]]


@dataclass(frozen=True)
class ParsedURL:
    url: str
    scheme: str
    host: str  # lowercase, IDNA (ascii), no trailing dot
    port: int
    parts: SplitResult

    @property
    def is_ip_literal(self) -> bool:
        return _as_ip(self.host) is not None


def _as_ip(host: str):
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def host_matches(host: str, domains: tuple[str, ...]) -> bool:
    """True if host equals a domain or is a subdomain of it (dot boundary)."""
    return any(host == d or host.endswith("." + d) for d in domains)


def parse_url(raw: str, allowed_ports: frozenset[int] = frozenset({80, 443})) -> ParsedURL:
    """Strict syntactic validation. Does not touch the network."""
    if not isinstance(raw, str):
        raise InvalidURL()
    raw = raw.strip()
    if not raw or len(raw) > MAX_URL_LENGTH:
        raise InvalidURL()
    if any(ord(c) <= 32 or ord(c) == 127 for c in raw) or "\\" in raw:
        raise InvalidURL("The URL contains invalid characters.")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise InvalidURL() from None
    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidURL("Only http and https links are supported.")
    if parts.username is not None or parts.password is not None or "@" in (parts.netloc or ""):
        raise InvalidURL("URLs with embedded credentials are not allowed.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise InvalidURL()
    if _as_ip(host) is None:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise InvalidURL() from None
        if host in BLOCKED_NAMES or host.endswith(BLOCKED_SUFFIXES):
            raise BlockedHost()
        labels = host.split(".")
        # Reject numeric/hex pseudo-IPs such as 2130706433 or 0x7f.1 (resolver quirks).
        last = labels[-1]
        if len(labels) < 2 or last.isdigit() or last.startswith("0x"):
            raise InvalidURL()
    scheme = parts.scheme.lower()
    port = port or (443 if scheme == "https" else 80)
    if port not in allowed_ports:
        raise BlockedHost("Only the standard web ports (80/443) are allowed.")
    return ParsedURL(url=raw, scheme=scheme, host=host, port=port, parts=parts)


def is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    """True only for globally routable unicast addresses (unwraps embedded IPv4)."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip in ipaddress.ip_network("64:ff9b::/96"):  # NAT64
            return is_public_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.sixtofour is not None:  # 2002::/16
            return is_public_ip(ip.sixtofour)
        if ip in ipaddress.ip_network("2001::/32"):  # Teredo
            return False
    return bool(ip.is_global) and not (
        ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved
    )


async def default_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise InvalidURL("The host name could not be resolved.") from None
    seen: list[str] = []
    for info in infos:
        addr = info[4][0].split("%")[0]
        if addr not in seen:
            seen.append(addr)
    return seen


async def resolve_public(parsed: ParsedURL, resolver: Resolver | None = None) -> list[str]:
    """Resolve host and require EVERY address to be public (anti DNS-rebinding
    pinning is done by the caller connecting to the returned IPs)."""
    literal = _as_ip(parsed.host)
    addrs = [str(literal)] if literal else await (resolver or default_resolver)(parsed.host, parsed.port)
    if not addrs:
        raise InvalidURL("The host name could not be resolved.")
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            raise BlockedHost() from None
        if not is_public_ip(ip):
            raise BlockedHost()
    return addrs
