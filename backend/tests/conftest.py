import pytest

from core.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(work_dir=tmp_path / "work", rate_limit_per_minute=1000)


def public_resolver(ip="93.184.216.34"):
    async def r(host, port):
        return [ip]
    return r
