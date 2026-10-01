"""End-to-end API tests with a fake extractor (no network)."""
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core.extractor.base import Extractor
from core.models import MediaFormat, MediaInfo, MediaItem, MediaKind
from core.service import MediaService
from tests.fakes import FakeFetcher

import subprocess


class FakeExtractor(Extractor):
    platform = "Fake"
    hosts = ("fake.test",)

    async def analyze(self, url):
        fmts = [MediaFormat(id="v1", kind=MediaKind.VIDEO, ext="mp4", height=64, has_audio=True),
                MediaFormat(id="a1", kind=MediaKind.AUDIO, ext="m4a", has_audio=True),
                MediaFormat(id="p1", kind=MediaKind.IMAGE, ext="png", is_preview=True)]
        return MediaInfo(platform="Fake", url=url, title="My ../Clip", items=[
            MediaItem(id="1", media_type=MediaKind.VIDEO, formats=fmts)])

    async def download(self, url, item, fmt, dest_dir, ctl):
        ctl.report("downloading", 1, 2)
        if getattr(self, "slow", False):
            import asyncio
            for _ in range(100):
                await asyncio.sleep(0.05)
                ctl.check()
        out = dest_dir / ("media.png" if fmt.kind == MediaKind.IMAGE else "media.mp4")
        if fmt.kind == MediaKind.IMAGE:
            from PIL import Image
            Image.new("RGB", (4, 4)).save(out)
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-f", "lavfi",
                            "-i", "color=s=32x32:d=1", "-shortest", str(out)], check=True)
        return out


@pytest.fixture
def client_factory(settings):
    clients = []

    def make(**overrides):
        s = replace(settings, **overrides)
        svc = MediaService(s, fetcher=FakeFetcher())
        ex = FakeExtractor(svc.registry.ctx)
        svc.registry._extractors.insert(0, ex)
        c = TestClient(create_app(s, svc))
        c.__enter__()
        clients.append(c)
        c.fake = ex
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def wait(c, jid, states=("ready", "failed", "cancelled"), headers=None):
    for _ in range(100):
        j = c.get(f"/v1/jobs/{jid}", headers=headers).json()
        if j["state"] in states:
            return j
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_health_and_analyze(client_factory):
    c = client_factory()
    assert "YouTube" in c.get("/healthz").json()["platforms"]
    r = c.post("/v1/analyze", json={"url": "https://fake.test/x"})
    assert r.status_code == 200 and r.json()["items"][0]["formats"][0]["id"] == "v1"
    assert "url" not in r.json()["items"][0]["formats"][0]


@pytest.mark.parametrize("url,status,code", [
    ("http://127.0.0.1/admin", 422, "UNSUPPORTED_URL"), ("http://localhost:8080/", 400, "BLOCKED_HOST"),
    ("file:///etc/passwd", 400, "INVALID_URL"), ("https://example.com/", 422, "UNSUPPORTED_URL"),
    ("javascript:alert(1)", 400, "INVALID_URL"), ("https://u:p@fake.test/", 400, "INVALID_URL"),
])
def test_analyze_errors_are_friendly(client_factory, url, status, code):
    r = client_factory().post("/v1/analyze", json={"url": url})
    assert r.status_code == status and r.json()["error"]["code"] == code and r.json()["error"]["message"]


def test_full_video_job_and_cleanup(client_factory, settings):
    c = client_factory()
    r = c.post("/v1/jobs", json={"url": "https://fake.test/x", "format_id": "v1"})
    assert r.status_code == 202
    jid = r.json()["id"]
    j = wait(c, jid)
    assert j["state"] == "ready" and j["file"]["content_type"] == "video/mp4"
    f = c.get(f"/v1/jobs/{jid}/file")
    assert f.status_code == 200 and len(f.content) == j["file"]["size"]
    assert "My_Clip.mp4" in f.headers["content-disposition"]
    assert f.headers["x-content-type-options"] == "nosniff"
    assert c.get(f"/v1/jobs/{jid}/file", headers={"Range": "bytes=0-9"}).status_code == 206
    assert any((settings.work_dir).iterdir())
    assert c.delete(f"/v1/jobs/{jid}").status_code == 204
    assert not any((settings.work_dir).iterdir())
    assert c.get(f"/v1/jobs/{jid}").status_code == 404


def test_audio_output_mp3(client_factory):
    c = client_factory()
    jid = c.post("/v1/jobs", json={"url": "https://fake.test/x", "output": "mp3"}).json()["id"]
    j = wait(c, jid)
    assert j["state"] == "ready" and j["file"]["content_type"] == "audio/mpeg"


def test_preview_needs_opt_in(client_factory):
    c = client_factory()
    jid = c.post("/v1/jobs", json={"url": "https://fake.test/x", "format_id": "p1"}).json()["id"]
    j = wait(c, jid)
    assert j["state"] == "failed" and j["error"]["code"] == "PREVIEW_ONLY"
    jid = c.post("/v1/jobs", json={"url": "https://fake.test/x", "format_id": "p1", "accept_preview": True}).json()["id"]
    assert wait(c, jid)["state"] == "ready"


def test_failed_job_leaves_no_files(client_factory, settings):
    c = client_factory()
    jid = c.post("/v1/jobs", json={"url": "https://fake.test/x", "format_id": "nope"}).json()["id"]
    j = wait(c, jid)
    assert j["error"]["code"] == "INVALID_REQUEST"
    assert not any(settings.work_dir.iterdir())


@pytest.mark.parametrize("body", [
    {"url": "https://fake.test/x", "output": "exe"},
    {"url": "https://fake.test/x", "format_id": "a b"},
    {"url": "https://fake.test/x", "format_id": "../../x"},
    {"url": "https://fake.test/" + "a" * 3000},
])
def test_job_input_validation(client_factory, body):
    assert client_factory().post("/v1/jobs", json=body).status_code in (400, 422)


def test_job_id_unguessable_and_scoped(client_factory):
    c = client_factory()
    jid = c.post("/v1/jobs", json={"url": "https://fake.test/x"}).json()["id"]
    assert len(jid) >= 24
    for bad in ("../etc", "x", "a" * 24):
        assert c.get(f"/v1/jobs/{bad}").status_code in (404, 400)


def test_per_client_active_job_limit_and_cancel(client_factory):
    c = client_factory(max_active_jobs_per_client=2, max_concurrent_jobs=2)
    c.fake.slow = True
    ids = [c.post("/v1/jobs", json={"url": "https://fake.test/x"}).json()["id"] for _ in range(2)]
    r = c.post("/v1/jobs", json={"url": "https://fake.test/x"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "BUSY"
    for i in ids:
        assert c.delete(f"/v1/jobs/{i}").status_code == 204
    time.sleep(0.3)
    assert c.get(f"/v1/jobs/{ids[0]}").status_code == 404


def test_job_timeout(client_factory):
    c = client_factory(job_timeout_seconds=1)
    c.fake.slow = True
    jid = c.post("/v1/jobs", json={"url": "https://fake.test/x"}).json()["id"]
    j = wait(c, jid)
    assert j["state"] == "failed" and j["error"]["code"] == "TIMEOUT"


def test_rate_limit(client_factory):
    c = client_factory(rate_limit_per_minute=3)
    codes = [c.get("/v1/jobs/aaaaaaaaaaaaaaaaaaaaaaaa").status_code for _ in range(5)]
    assert codes[:3] == [404] * 3 and codes[3:] == [429, 429]


def test_api_key(client_factory):
    c = client_factory(api_key="s3cret")
    body = {"url": "https://fake.test/x"}
    assert c.post("/v1/analyze", json=body).status_code == 401
    assert c.post("/v1/analyze", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/v1/analyze", json=body, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.get("/healthz").status_code == 200


def test_sse_events(client_factory):
    c = client_factory()
    jid = c.post("/v1/jobs", json={"url": "https://fake.test/x"}).json()["id"]
    r = c.get(f"/v1/jobs/{jid}/events")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert '"state": "ready"' in r.text
