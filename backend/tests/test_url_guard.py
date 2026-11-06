import pytest

from core.errors import BlockedHost, InvalidURL
from core.security.url_guard import host_matches, parse_url, resolve_public


@pytest.mark.parametrize("url", [
    "", "   ", "not a url", "ftp://example.com/x", "file:///etc/passwd", "gopher://example.com",
    "javascript:alert(1)", "data:text/html,hi", "http://", "https://user:pw@example.com/",
    "https://example.com@evil.com/", "https://exa mple.com/", "https://example.com\\@evil.com",
    "http://2130706433/", "http://0x7f.1/", "http://127.1/", "https://example/", "x" * 3000,
    "https://exam\x00ple.com/",
])
def test_invalid_urls(url):
    with pytest.raises((InvalidURL, BlockedHost)):
        parse_url(url)


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://foo.localhost/", "http://printer.local/", "http://x.internal/",
    "http://metadata.google.internal/", "https://example.com:8443/", "http://example.com:22/",
])
def test_blocked_hosts_and_ports(url):
    with pytest.raises(BlockedHost):
        parse_url(url)


def test_valid_url_normalised():
    p = parse_url("HTTPS://WWW.YouTube.com./watch?v=abc")
    assert (p.scheme, p.host, p.port) == ("https", "www.youtube.com", 443)


def test_idna_host():
    assert parse_url("https://bücher.example/").host == "xn--bcher-kva.example"


def test_host_matches_dot_boundary():
    assert host_matches("www.youtube.com", ("youtube.com",))
    assert host_matches("youtube.com", ("youtube.com",))
    assert not host_matches("evilyoutube.com", ("youtube.com",))
    assert not host_matches("youtube.com.evil.com", ("youtube.com",))


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.0.1",
    "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1",
    "2002:7f00:1::", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "255.255.255.255",
])
async def test_literal_private_ips_blocked(ip):
    host = f"[{ip}]" if ":" in ip else ip
    parsed = parse_url(f"http://{host}/")
    with pytest.raises(BlockedHost):
        await resolve_public(parsed)


async def test_public_literal_ok():
    assert await resolve_public(parse_url("http://93.184.216.34/")) == ["93.184.216.34"]


async def test_resolved_private_blocked_even_if_mixed():
    async def r(h, p):
        return ["93.184.216.34", "10.0.0.1"]
    with pytest.raises(BlockedHost):
        await resolve_public(parse_url("https://example.com/"), r)


async def test_empty_resolution():
    async def r(h, p):
        return []
    with pytest.raises(InvalidURL):
        await resolve_public(parse_url("https://example.com/"), r)
