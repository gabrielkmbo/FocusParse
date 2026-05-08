from __future__ import annotations

from io import BytesIO

from PIL import Image

from focusparse.models.images import model_image_max_dim, read_model_image_bytes


def _write_png(path, *, size: tuple[int, int]) -> bytes:
    img = Image.new("RGB", size, "white")
    img.save(path)
    return path.read_bytes()


def _image_size(data: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(data)) as img:
        return img.size


def test_model_image_max_dim_default_env_and_disable(monkeypatch):
    monkeypatch.delenv("FOCUSPARSE_MODEL_IMAGE_MAX_DIM", raising=False)
    assert model_image_max_dim() == 2048

    monkeypatch.setenv("FOCUSPARSE_MODEL_IMAGE_MAX_DIM", "1024")
    assert model_image_max_dim() == 1024

    monkeypatch.setenv("FOCUSPARSE_MODEL_IMAGE_MAX_DIM", "128")
    assert model_image_max_dim() == 256

    monkeypatch.setenv("FOCUSPARSE_MODEL_IMAGE_MAX_DIM", "0")
    assert model_image_max_dim() == 0


def test_read_model_image_bytes_keeps_small_images_unchanged(tmp_path):
    path = tmp_path / "small.png"
    original = _write_png(path, size=(320, 180))

    assert read_model_image_bytes(path, max_dim=2048) == original


def test_read_model_image_bytes_downscales_large_images(tmp_path):
    path = tmp_path / "large.png"
    _write_png(path, size=(3000, 1500))

    data = read_model_image_bytes(path, max_dim=1000)

    assert _image_size(data) == (1000, 500)


def test_read_model_image_bytes_can_disable_downscaling(tmp_path):
    path = tmp_path / "large.png"
    original = _write_png(path, size=(3000, 1500))

    assert read_model_image_bytes(path, max_dim=0) == original
