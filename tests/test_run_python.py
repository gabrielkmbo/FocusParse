"""Tests for `focusparse.tools.run_python` — sandboxed code execution.

Covers:
  * Simple code runs and stdout captures
  * Disallowed imports raise ImportError inside the sandbox
  * `open()` and `eval()` builtins are blocked
  * Wall-time timeout terminates infinite loops
  * Image input/output round-trip via `images` dict + `save_image()` helper
  * Image refs are content-addressed (sha256 prefix)
  * Image cache miss is silent (empty `images` dict, no crash)

These tests spawn real subprocesses, so they're slower than the rest of the
suite. Marked `slow` so devs can skip with `-m "not slow"` when iterating.
"""

from __future__ import annotations

import sys

import pytest
from PIL import Image

from focusparse.tools.run_python import RunPythonInput, run_python

pytestmark = pytest.mark.asyncio


# Each test forks a child via `multiprocessing` — keep counts low and skip
# entirely on CI runners that don't have a working `fork`/`spawn` context.
if sys.platform == "win32":
    pytest.skip("run_python uses multiprocessing.spawn; skip on Windows", allow_module_level=True)


async def test_simple_code_runs_and_captures_stdout():
    out = await run_python(RunPythonInput(code="print('hello world')"))
    assert out.exit_code == 0
    assert "hello world" in out.stdout
    assert out.timed_out is False


async def test_disallowed_import_blocked():
    code = "import os\nprint(os.getcwd())"
    out = await run_python(RunPythonInput(code=code))
    # Import gate raises ImportError inside the child; that gets reported
    # via traceback to stderr, exit_code != 0.
    assert out.exit_code != 0
    assert "Sandbox" in out.stderr or "not allowed" in out.stderr or "ImportError" in out.stderr


async def test_disallowed_import_subprocess_module_blocked():
    code = "import subprocess\nsubprocess.run(['ls'])"
    out = await run_python(RunPythonInput(code=code))
    assert out.exit_code != 0


async def test_open_builtin_blocked():
    """open() is removed from __builtins__ in the sandbox."""
    code = "f = open('/etc/passwd', 'r')\nprint(f.read())"
    out = await run_python(RunPythonInput(code=code))
    # NameError because open isn't in builtins.
    assert out.exit_code != 0
    assert "open" in out.stderr or "NameError" in out.stderr


async def test_eval_builtin_blocked():
    code = "x = eval('2 + 2')\nprint(x)"
    out = await run_python(RunPythonInput(code=code))
    assert out.exit_code != 0


async def test_wall_time_timeout_kills_infinite_loop():
    code = "while True:\n    pass"
    out = await run_python(RunPythonInput(code=code, wall_time_s=2))
    assert out.timed_out is True


async def test_image_round_trip_via_save_image(tmp_path):
    """Pass an image in via image_refs, transform it, save_image() it back."""
    # Set up cache: write a small PNG with a known cache key.
    src = Image.new("RGB", (64, 64), color=(255, 0, 0))
    src.save(tmp_path / "redbox.png", format="PNG")

    code = """
img = images["redbox"]
out = img.resize((128, 128))
print("resized to", out.size)
save_image(out)
"""
    res = await run_python(
        RunPythonInput(code=code, image_refs=["redbox"]),
        image_cache_dir=tmp_path,
    )
    assert res.exit_code == 0, res.stderr
    assert "resized to (128, 128)" in res.stdout
    assert len(res.new_image_refs) == 1
    # Output PNG was written under the new-image cache dir.
    out_path = tmp_path / f"{res.new_image_refs[0]}.png"
    assert out_path.exists()
    with Image.open(out_path) as im:
        assert im.size == (128, 128)


async def test_image_cache_miss_is_silent(tmp_path):
    """Missing ref → images dict missing the key, no exception raised."""
    code = """
print("len(images) =", len(images))
print("got" if "missing" in images else "no key")
"""
    res = await run_python(
        RunPythonInput(code=code, image_refs=["missing"]),
        image_cache_dir=tmp_path,
    )
    assert res.exit_code == 0
    assert "len(images) = 0" in res.stdout
    assert "no key" in res.stdout


async def test_new_image_ref_is_content_addressed(tmp_path):
    """Same image saved twice → same ref (deterministic sha256 prefix)."""
    src = Image.new("RGB", (32, 32), color=(0, 0, 255))
    src.save(tmp_path / "blue.png", format="PNG")

    code = """
img = images["blue"]
save_image(img)
save_image(img)
"""
    res = await run_python(
        RunPythonInput(code=code, image_refs=["blue"]),
        image_cache_dir=tmp_path,
    )
    assert res.exit_code == 0
    # Both saves produce the same content-addressed ref.
    assert len(res.new_image_refs) == 2
    assert res.new_image_refs[0] == res.new_image_refs[1]


async def test_exception_traceback_captured_to_stderr():
    """User code that raises: traceback goes to stderr, exit_code=1."""
    code = "raise RuntimeError('intentional sandbox error')"
    res = await run_python(RunPythonInput(code=code))
    assert res.exit_code == 1
    assert "intentional sandbox error" in res.stderr
    assert "RuntimeError" in res.stderr


async def test_lanczos_supersample_works(tmp_path):
    """Smoke: the actual high-res zoom workflow — crop + LANCZOS upsample."""
    # Make a small striped PNG to upsample.
    src = Image.new("RGB", (10, 10), color=(0, 0, 0))
    for y in range(0, 10, 2):
        for x in range(10):
            src.putpixel((x, y), (255, 255, 255))
    src.save(tmp_path / "tiny.png", format="PNG")

    code = """
from PIL import Image
img = images["tiny"]
big = img.resize((40, 40), Image.Resampling.LANCZOS)
print("ok", big.size)
save_image(big)
"""
    res = await run_python(
        RunPythonInput(code=code, image_refs=["tiny"]),
        image_cache_dir=tmp_path,
    )
    assert res.exit_code == 0, res.stderr
    assert "ok (40, 40)" in res.stdout
    assert len(res.new_image_refs) == 1
