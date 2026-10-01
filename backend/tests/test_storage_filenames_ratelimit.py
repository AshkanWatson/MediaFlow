import os

import pytest

from core.errors import Busy, InvalidRequest, RateLimited
from core.security import RateLimiter, confine, sanitize_filename
from core.storage import JobStorage


@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b\\c:d*?", "", "CON", "..", "h\u00e9llo w\u00f6rld",
                                  "x" * 500, "evil\r\nheader: x"])
def test_sanitize_is_harmless(name):
    out = sanitize_filename(name, "mp4")
    assert out.endswith(".mp4")
    assert not any(c in out for c in "/\\\r\n:") and ".." not in out and len(out) <= 84


def test_sanitize_fallbacks():
    assert sanitize_filename("", "mp4") == "media.mp4"
    assert sanitize_filename("CON", "mp4") == "media.mp4"
    assert sanitize_filename("h\u00e9llo", "jpg") == "hello.jpg"


def test_sanitize_ext_cleaned():
    assert sanitize_filename("a", "m/p4;rm").endswith(".mp4rm")


def test_confine(tmp_path):
    (tmp_path / "a").mkdir()
    assert confine(tmp_path, tmp_path / "a" / "f") == (tmp_path / "a" / "f").resolve()
    with pytest.raises(InvalidRequest):
        confine(tmp_path, tmp_path / ".." / "x")
    link = tmp_path / "a" / "link"
    os.symlink("/etc", link)
    with pytest.raises(InvalidRequest):
        confine(tmp_path, link / "passwd")


def test_storage_lifecycle(tmp_path):
    st = JobStorage(tmp_path / "w", quota_bytes=10)
    d = st.create("a" * 24)
    (d / "f").write_bytes(b"123")
    assert st.usage() == 3
    st.remove("a" * 24)
    assert not d.exists()


@pytest.mark.parametrize("bad", ["../x", "short", "a/b" + "c" * 20, "", "x" * 100])
def test_storage_rejects_bad_ids(tmp_path, bad):
    with pytest.raises(InvalidRequest):
        JobStorage(tmp_path, 10).job_dir(bad)


def test_storage_quota(tmp_path):
    st = JobStorage(tmp_path / "w", quota_bytes=5)
    d = st.create("a" * 24)
    (d / "f").write_bytes(b"x" * 10)
    with pytest.raises(Busy):
        st.create("b" * 24)


def test_purge_stale(tmp_path):
    st = JobStorage(tmp_path / "w", 100)
    st.create("a" * 24)
    st.create("b" * 24)
    assert st.purge_stale(0, keep={"a" * 24}) == 1
    assert st.job_dir("a" * 24).exists() and not st.job_dir("b" * 24).exists()


def test_rate_limiter_window():
    t = [0.0]
    rl = RateLimiter(2, window=10, clock=lambda: t[0])
    rl.check("a"); rl.check("a")
    with pytest.raises(RateLimited):
        rl.check("a")
    rl.check("b")
    t[0] = 11
    rl.check("a")
