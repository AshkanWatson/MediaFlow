import subprocess
from dataclasses import replace

import pytest
from PIL import Image

from core.errors import InvalidMedia, ProcessingFailed, TooLarge
from core.processor import Processor


@pytest.fixture
def sample_mp4(tmp_path):
    p = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-shortest", str(p)], check=True)
    return p


async def test_validate_av_ok(settings, sample_mp4):
    info = await Processor(settings).validate_av(sample_mp4)
    assert info["streams"]


async def test_validate_av_rejects_garbage(settings, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"<html>not media</html>" * 10)
    with pytest.raises(InvalidMedia):
        await Processor(settings).validate_av(bad)


async def test_validate_av_size_and_duration_limits(settings, sample_mp4):
    with pytest.raises(TooLarge):
        await Processor(replace(settings, max_file_bytes=10)).validate_av(sample_mp4)
    with pytest.raises(InvalidMedia):
        await Processor(replace(settings, max_duration_seconds=0)).validate_av(sample_mp4)


@pytest.mark.parametrize("fmt", ["mp3", "m4a"])
async def test_extract_audio(settings, sample_mp4, fmt):
    out = await Processor(settings).extract_audio(sample_mp4, sample_mp4.parent, fmt)
    assert out.suffix == f".{fmt}"
    info = await Processor(settings).validate_av(out)
    assert all(s["codec_type"] == "audio" for s in info["streams"])


async def test_extract_audio_unknown_format_rejected(settings, sample_mp4):
    with pytest.raises(ProcessingFailed):
        await Processor(settings).extract_audio(sample_mp4, sample_mp4.parent, "mp3; rm -rf /")


async def test_extract_audio_outside_job_dir_rejected(settings, sample_mp4, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(Exception):
        await Processor(settings).extract_audio(sample_mp4, other, "mp3")


async def test_filename_with_option_like_name_is_not_an_option(settings, sample_mp4, tmp_path):
    odd = tmp_path / "-i evil.mp4"
    sample_mp4.rename(odd)
    # path is passed as absolute, so a leading '-' cannot be parsed as an ffmpeg option
    out = await Processor(settings).extract_audio(odd, tmp_path, "mp3")
    assert out.exists()


def test_validate_image(settings, tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(p)
    assert Processor(settings).validate_image(p) == "png"


def test_validate_image_rejects_non_image_and_bombs(settings, tmp_path):
    bad = tmp_path / "a.jpg"
    bad.write_bytes(b"GIF-not-really")
    with pytest.raises(InvalidMedia):
        Processor(settings).validate_image(bad)
    p = tmp_path / "big.png"
    Image.new("RGB", (100, 100)).save(p)
    with pytest.raises(InvalidMedia):
        Processor(replace(settings, max_image_pixels=500)).validate_image(p)


def test_validate_image_rejects_svg(settings, tmp_path):
    p = tmp_path / "a.svg"
    p.write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
    with pytest.raises(InvalidMedia):
        Processor(settings).validate_image(p)
