"""HTTP client for untrusted URLs: DNS-pinned, redirect-validated, size/time capped."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import httpx

from core.config import Settings
from core.errors import DownloadTimeout, TooLarge, UpstreamError
from core.security.url_guard import Resolver, parse_url, resolve_public

REDIRECT_CODES = {301, 302, 303, 307, 308}
ProgressCb = Callable[[int, int | None], None]


@dataclass
class FetchResponse:
    url: str
    status: int
    headers: httpx.Headers
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class SafeFetcher:
    """Every hop (initial request and each redirect) is re-validated; the TCP
    connection goes to the validated IP, so a rebinding DNS answer can't win."""

    def __init__(self, settings: Settings, resolver: Resolver | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self._resolver = resolver
        self._client = httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": settings.user_agent, "Accept-Encoding": "identity"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def open(self, url: str, accept: str = "*/*") -> httpx.Response:
        """Return an open streaming response for the final (non-redirect) hop.
        Caller must close it."""
        current = url
        for _ in range(self.s.max_redirects + 1):
            parsed = parse_url(current, self.s.allowed_ports)
            addrs = await resolve_public(parsed, self._resolver)
            resp = await self._send_pinned(parsed, addrs, accept)
            if resp.status_code in REDIRECT_CODES and resp.headers.get("location"):
                loc = resp.headers["location"]
                await resp.aclose()
                current = urljoin(current, loc)
                continue
            return resp
        raise UpstreamError("Too many redirects.")

    async def _send_pinned(self, parsed, addrs: list[str], accept: str) -> httpx.Response:
        last: Exception | None = None
        for addr in addrs[:3]:
            target = httpx.URL(parsed.url).copy_with(host=addr)
            req = httpx.Request(
                "GET", target,
                headers={"Host": parsed.host, "Accept": accept},
                extensions={"sni_hostname": parsed.host},
            )
            try:
                return await self._client.send(req, stream=True)
            except httpx.TimeoutException:
                last = DownloadTimeout()
            except httpx.HTTPError as e:
                last = UpstreamError(f"Could not reach the host ({type(e).__name__}).")
        raise last or UpstreamError()

    async def get_bytes(self, url: str, max_bytes: int | None = None, accept: str = "*/*") -> FetchResponse:
        limit = max_bytes or self.s.max_page_bytes
        resp = await self.open(url, accept)
        try:
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise TooLarge()
            buf = bytearray()
            async for chunk in resp.aiter_bytes(65536):
                buf += chunk
                if len(buf) > limit:
                    raise TooLarge()
            return FetchResponse(str(resp.url), resp.status_code, resp.headers, bytes(buf))
        except httpx.TimeoutException:
            raise DownloadTimeout() from None
        except httpx.HTTPError:
            raise UpstreamError() from None
        finally:
            await resp.aclose()

    async def download_to(self, url: str, dest: Path, max_bytes: int, deadline: float | None = None,
                          progress: ProgressCb | None = None, check: Callable[[], None] | None = None,
                          accept: str = "*/*") -> httpx.Headers:
        """Stream to `dest` (caller chooses a server-generated path). Writes to
        a .part file and renames atomically."""
        resp = await self.open(url, accept)
        part = dest.with_name(dest.name + ".part")
        try:
            if resp.status_code != 200:
                raise UpstreamError(f"The source returned HTTP {resp.status_code}.")
            total = resp.headers.get("content-length")
            total_i = int(total) if total and total.isdigit() else None
            if total_i is not None and total_i > max_bytes:
                raise TooLarge()
            done = 0
            with part.open("wb") as fh:
                async for chunk in resp.aiter_bytes(65536):
                    done += len(chunk)
                    if done > max_bytes:
                        raise TooLarge()
                    if deadline is not None and time.monotonic() > deadline:
                        raise DownloadTimeout()
                    if check:
                        check()
                    fh.write(chunk)
                    if progress:
                        progress(done, total_i)
            part.replace(dest)
            return resp.headers
        except httpx.TimeoutException:
            raise DownloadTimeout() from None
        except httpx.HTTPError:
            raise UpstreamError() from None
        finally:
            await resp.aclose()
            part.unlink(missing_ok=True)
