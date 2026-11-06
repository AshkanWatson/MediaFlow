import httpx
import pytest

from core.errors import BlockedHost, TooLarge, UpstreamError
from core.security import SafeFetcher
from tests.conftest import public_resolver


def make(settings, handler, resolver=None):
    return SafeFetcher(settings, resolver or public_resolver(), httpx.MockTransport(handler))


async def test_connects_to_pinned_ip_with_host_and_sni(settings):
    seen = {}

    def h(req):
        seen.update(host=req.url.host, header=req.headers["host"], sni=req.extensions["sni_hostname"])
        return httpx.Response(200, content=b"hi")

    f = make(settings, h)
    r = await f.get_bytes("https://example.com/p")
    assert r.body == b"hi"
    assert seen == {"host": "93.184.216.34", "header": "example.com", "sni": "example.com"}


async def test_redirect_to_private_ip_blocked(settings):
    def h(req):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    with pytest.raises(BlockedHost):
        await make(settings, h).get_bytes("https://example.com/")


async def test_redirect_to_hostname_resolving_private_blocked(settings):
    calls = []

    async def resolver(host, port):
        calls.append(host)
        return ["93.184.216.34"] if host == "example.com" else ["10.1.1.1"]

    def h(req):
        return httpx.Response(301, headers={"location": "https://intranet-app.example.org/"})

    with pytest.raises(BlockedHost):
        await make(settings, h, resolver).get_bytes("https://example.com/")
    assert calls == ["example.com", "intranet-app.example.org"]


async def test_redirect_to_non_http_scheme_blocked(settings):
    def h(req):
        return httpx.Response(302, headers={"location": "file:///etc/passwd"})

    with pytest.raises(Exception) as e:
        await make(settings, h).get_bytes("https://example.com/")
    assert e.value.code == "INVALID_URL"


async def test_redirect_loop_limited(settings):
    def h(req):
        return httpx.Response(302, headers={"location": "https://example.com/again"})

    with pytest.raises(UpstreamError):
        await make(settings, h).get_bytes("https://example.com/")


async def test_dns_rebinding_each_hop_revalidated(settings):
    n = {"c": 0}

    async def resolver(host, port):
        n["c"] += 1
        return ["93.184.216.34"] if n["c"] == 1 else ["127.0.0.1"]

    def h(req):
        return httpx.Response(302, headers={"location": "https://example.com/second"})

    with pytest.raises(BlockedHost):
        await make(settings, h, resolver).get_bytes("https://example.com/")


async def test_body_size_cap_streamed(settings):
    def h(req):
        return httpx.Response(200, content=b"x" * 5000)

    with pytest.raises(TooLarge):
        await make(settings, h).get_bytes("https://example.com/", max_bytes=1000)


async def test_content_length_precheck(settings):
    def h(req):
        return httpx.Response(200, headers={"content-length": "999999"}, content=b"x")

    with pytest.raises(TooLarge):
        await make(settings, h).get_bytes("https://example.com/", max_bytes=1000)


async def test_download_to_cap_and_cleanup(settings, tmp_path):
    def h(req):
        return httpx.Response(200, content=b"y" * 5000)

    dest = tmp_path / "f.bin"
    with pytest.raises(TooLarge):
        await make(settings, h).download_to("https://example.com/f", dest, max_bytes=1000)
    assert not dest.exists() and not (tmp_path / "f.bin.part").exists()


async def test_download_to_success_atomic(settings, tmp_path):
    def h(req):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"abc")

    dest = tmp_path / "f.bin"
    hdrs = await make(settings, h).download_to("https://example.com/f", dest, max_bytes=1000)
    assert dest.read_bytes() == b"abc" and hdrs["content-type"] == "image/png"
    assert not (tmp_path / "f.bin.part").exists()


async def test_download_non_200(settings, tmp_path):
    def h(req):
        return httpx.Response(404)

    with pytest.raises(UpstreamError):
        await make(settings, h).download_to("https://example.com/f", tmp_path / "f", max_bytes=10)


async def test_port_not_allowed(settings):
    with pytest.raises(BlockedHost):
        await make(settings, lambda r: httpx.Response(200)).get_bytes("https://example.com:6379/")
