"""run_python — sandboxed code execution for coding-driven zoom.

**This is the high-resolution zoom mechanism.** The model writes Python that
crops, super-samples (e.g. LANCZOS 2× on a 10-pixel-tall axis label), annotates,
or computes over prior crops, and the transformed output becomes a new virtual
image the model can re-inspect.

Security posture (research-grade, **not** production-isolation):
  - Runs in a subprocess via `multiprocessing.Process`, never `exec`/`eval`
    in-process.
  - `resource.setrlimit(RLIMIT_CPU, 15)` + `RLIMIT_AS` for memory.
  - Wall-time watchdog joins/terminates the child on timeout.
  - Import allowlist enforced via a custom `MetaPathFinder` installed at the
    top of `sys.meta_path` in the child, so `import os` and friends raise
    `ImportError` immediately. The pre-loaded allowlist (`PIL`, `numpy`,
    `matplotlib`, `scipy`) is imported BEFORE the finder is installed so the
    child has those at hand.
  - Tool input is code + content-addressed `image_refs`; the parent resolves
    the actual bytes from the cache, the child sees a `images: dict[str,
    PIL.Image]` global.

NEVER deploy FocusParse to accept untrusted questions — the sandbox is
sufficient for research, not adversarial defense. A determined attacker can
escape via shared-memory tricks or by abusing allowed modules; the threat
model is "we wrote this code ourselves, but we want a guard against
runaway loops + unintended side effects".
"""

from __future__ import annotations

import hashlib
import multiprocessing as mp
import os
import sys
import traceback
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, Field

ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageEnhance",
        "PIL.ImageFilter",
        "PIL.ImageOps",
        "numpy",
        "numpy.linalg",
        "numpy.random",
        "matplotlib",
        "matplotlib.pyplot",
        "scipy",
        "scipy.ndimage",
        "scipy.signal",
        # Standard-library leaves the model can use safely. Anything that
        # opens sockets / files-by-path / processes is NOT here on purpose.
        "io",
        "math",
        "statistics",
        "hashlib",
        "json",
        "base64",
        "itertools",
        "functools",
    }
)

DEFAULT_WALL_TIME_S = 15
DEFAULT_CPU_S = 15
DEFAULT_RSS_MB = 1024


_RUN_PYTHON_CODE_EXAMPLE = (
    "from PIL import Image\n"
    "ref = image_refs[0]\n"
    "img = images[ref]\n"
    "out = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)\n"
    "print('upsampled', img.size, '->', out.size)\n"
    "save_image(out)\n"
)


class RunPythonInput(BaseModel):
    code: str = Field(
        ...,
        description=(
            "Python source. The sandbox exposes `images: dict[str, "
            "PIL.Image]` keyed by the strings you pass in `image_refs`, "
            "and `save_image(img)` to return new PNGs. `print(...)` output "
            "is captured into stdout. Allowlist: PIL, numpy, matplotlib, "
            "scipy, plus io/math/statistics/hashlib/json/base64/itertools/"
            "functools. Forbidden: os, subprocess, open(), exec(), eval(), "
            "socket. Wall-time cap is 15s by default."
        ),
        examples=[_RUN_PYTHON_CODE_EXAMPLE],
    )
    image_refs: list[str] = Field(
        default_factory=list,
        description=(
            "Refs to images to expose inside the sandbox as `images[ref]`. "
            "Accepts either 16-char content-addressed cache stems (from a "
            "prior run_python's `new_image_refs`) OR absolute paths (e.g. "
            "an `inspect_region.crop_ref`)."
        ),
        examples=[["/Users/me/cache/crops/abc123.png"]],
    )
    wall_time_s: int = Field(
        default=DEFAULT_WALL_TIME_S,
        ge=1,
        le=60,
        description="Wall-time budget in seconds; sandbox is killed past this.",
    )


class RunPythonOutput(BaseModel):
    stdout: str = Field(..., description="Captured stdout from `print(...)` calls in the sandbox.")
    stderr: str = Field(
        default="",
        description="Captured stderr; populated on exceptions or timeouts.",
    )
    new_image_refs: list[str] = Field(
        default_factory=list,
        description=(
            "16-char sha256 stems for each PNG saved via `save_image(img)`. "
            "Re-feed these strings as `run_python.image_refs` in a "
            "subsequent call to chain transformations."
        ),
    )
    exit_code: int = Field(
        default=0, description="0 on success, 1 on Python exception, 2 on infrastructure error."
    )
    timed_out: bool = Field(
        default=False,
        description="True if the sandbox was killed by the wall-time watchdog.",
    )


async def run_python(
    inp: RunPythonInput,
    *,
    image_cache_dir: Path | None = None,
    new_image_cache_dir: Path | None = None,
) -> RunPythonOutput:
    """Execute `inp.code` in a sandboxed subprocess.

    Args:
        inp: code + image_refs + wall_time_s.
        image_cache_dir: directory containing cached crops (PNGs named by
            their cache key — the same dir `inspect_region` writes to).
            When None, the child gets an empty `images` dict.
        new_image_cache_dir: where to persist new images the code produces
            via `save_image(img)` helper. Defaults to `image_cache_dir`.

    Returns:
        RunPythonOutput with stdout/stderr from the subprocess, any new
        image refs (content-addressed sha256 of PNG bytes), and exit/timeout
        flags.
    """
    new_image_cache_dir = new_image_cache_dir or image_cache_dir
    if new_image_cache_dir is not None:
        new_image_cache_dir = Path(new_image_cache_dir)
        new_image_cache_dir.mkdir(parents=True, exist_ok=True)

    # Resolve cached image bytes in the parent so the child never sees the
    # cache-dir path (no path-injection vector through the model).
    image_payloads: dict[str, bytes] = {}
    if image_cache_dir is not None:
        cache_root = Path(image_cache_dir)
        for ref in inp.image_refs:
            for ext in (".png", ".jpg", ".jpeg"):
                candidate = cache_root / f"{ref}{ext}"
                if candidate.exists():
                    image_payloads[ref] = candidate.read_bytes()
                    break
            else:
                # Bare ref (already an absolute path?) — try as-is.
                p = Path(ref)
                if p.exists():
                    image_payloads[ref] = p.read_bytes()

    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_child_main,
        args=(
            child_conn,
            inp.code,
            image_payloads,
            DEFAULT_CPU_S,
            DEFAULT_RSS_MB,
        ),
    )
    proc.start()
    proc.join(timeout=inp.wall_time_s)

    timed_out = proc.is_alive()
    if timed_out:
        proc.terminate()
        proc.join(timeout=2)
        if proc.is_alive():
            proc.kill()
            proc.join()

    payload: dict | None = None
    if parent_conn.poll(timeout=0.1):
        try:
            payload = parent_conn.recv()
        except (EOFError, ConnectionResetError):
            payload = None
    parent_conn.close()

    if payload is None:
        return RunPythonOutput(
            stdout="",
            stderr="(child produced no output)" if not timed_out else "(timed out)",
            exit_code=proc.exitcode if proc.exitcode is not None else -1,
            timed_out=timed_out,
        )

    new_refs: list[str] = []
    for png_bytes in payload.get("images", []):
        ref = hashlib.sha256(png_bytes).hexdigest()[:16]
        if new_image_cache_dir is not None:
            (new_image_cache_dir / f"{ref}.png").write_bytes(png_bytes)
        new_refs.append(ref)

    # Use the payload's exit_code (set by the user-code try/except) rather
    # than `proc.exitcode` (always 0 because the child wraps with os._exit(0)
    # to keep the pipe send sequence clean).
    payload_exit = payload.get("exit_code")
    return RunPythonOutput(
        stdout=payload.get("stdout", ""),
        stderr=payload.get("stderr", ""),
        new_image_refs=new_refs,
        exit_code=int(payload_exit) if payload_exit is not None else -1,
        timed_out=timed_out,
    )


# ---------------------------------------------------------------------------
# Child-process entry point
# ---------------------------------------------------------------------------


def _child_main(
    pipe,
    code: str,
    image_payloads: dict[str, bytes],
    cpu_s: int,
    rss_mb: int,
) -> None:
    """Child entry. Imports the allowlist, installs the import gate, runs code."""
    import contextlib
    import importlib

    stdout_buf = BytesIO()
    stderr_buf = BytesIO()

    try:
        # Set rlimits FIRST so any later overshoot kills the child.
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
            resource.setrlimit(resource.RLIMIT_AS, (rss_mb * 1024 * 1024, rss_mb * 1024 * 1024))
        except (ImportError, ValueError, OSError):
            # `resource` isn't available on Windows; skip there. The parent's
            # wall-time watchdog still protects us.
            pass

        # Pre-load allowlist via importlib so dotted names (`PIL.Image`)
        # return the leaf module, not the parent package.
        preloaded = {}
        for name in ALLOWED_IMPORTS:
            try:
                preloaded[name] = importlib.import_module(name)
            except ImportError:
                # Optional modules (matplotlib, scipy) may be missing in
                # minimal environments; skip silently.
                pass

        # Build the namespace the code runs in.
        builtins_dict = _safe_builtins()
        # Override __import__ to gate every import statement against the
        # allowlist. Python's import statement consults
        # `__builtins__.__import__`, which is more reliable than a meta_path
        # finder (which gets bypassed when the target module is already in
        # `sys.modules` — and `os` etc. ARE already in there from the parent).
        builtins_dict["__import__"] = _make_safe_import(ALLOWED_IMPORTS)

        ns: dict = {
            "__name__": "__sandbox__",
            "__builtins__": builtins_dict,
            "images": _decode_images(image_payloads, preloaded.get("PIL.Image")),
            "save_image": _make_save_image(preloaded.get("PIL.Image")),
            "_new_images_buffer": [],
        }

        # Run the user code with stdout/stderr captured.
        sys.stdout = _FdWriter(stdout_buf)
        sys.stderr = _FdWriter(stderr_buf)

        with contextlib.suppress(SystemExit):
            try:
                exec(compile(code, "<sandbox>", "exec"), ns)
                exit_code = 0
            except Exception:
                traceback.print_exc()
                exit_code = 1

        # Pull saved images out of the namespace.
        new_image_bytes: list[bytes] = list(ns.get("_new_images_buffer", []))

        pipe.send(
            {
                "stdout": stdout_buf.getvalue().decode("utf-8", errors="replace"),
                "stderr": stderr_buf.getvalue().decode("utf-8", errors="replace"),
                "images": new_image_bytes,
                "exit_code": exit_code,
            }
        )
    except Exception:
        # Last-ditch: report whatever we managed to capture.
        try:
            pipe.send(
                {
                    "stdout": stdout_buf.getvalue().decode("utf-8", errors="replace"),
                    "stderr": (
                        stderr_buf.getvalue().decode("utf-8", errors="replace")
                        + "\n"
                        + traceback.format_exc()
                    ),
                    "images": [],
                    "exit_code": 2,
                }
            )
        except Exception:
            pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass
        os._exit(0)


# ---------------------------------------------------------------------------
# Sandbox helpers (child-process side)
# ---------------------------------------------------------------------------


def _make_safe_import(allowlist: frozenset[str]):
    """Return a `__import__` replacement that blocks imports outside `allowlist`.

    Sub-modules of allowed packages are allowed (so `PIL._util` works for PIL).
    The real `__import__` is captured at function-definition time so swapping
    `__builtins__.__import__` doesn't recurse into the gate.
    """
    real_import = __import__

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Allowlist check on the top-level + dotted root of `name`.
        if name in allowlist:
            return real_import(name, globals, locals, fromlist, level)
        for allowed in allowlist:
            if name == allowed or name.startswith(allowed + "."):
                return real_import(name, globals, locals, fromlist, level)
        # Also check `fromlist` items against allowlist when `name` itself
        # is allowed (e.g. `from PIL import Image` ⇒ name="PIL", fromlist=["Image"];
        # already handled by the prefix check above).
        raise ImportError(f"Sandbox: import of {name!r} is not allowed")

    return safe_import


def _safe_builtins() -> dict:
    """Allowlist of builtins the sandbox code can use.

    Excludes: open, exec, eval, compile, __import__, input, exit, quit,
    breakpoint, help. Common math/iter/print stays.
    """
    import builtins

    safe = {
        "abs",
        "all",
        "any",
        "ascii",
        "bin",
        "bool",
        "bytearray",
        "bytes",
        "callable",
        "chr",
        "complex",
        "dict",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "getattr",
        "globals",
        "hasattr",
        "hash",
        "hex",
        "id",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "locals",
        "map",
        "max",
        "memoryview",
        "min",
        "next",
        "object",
        "oct",
        "ord",
        "pow",
        "print",
        "property",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "setattr",
        "slice",
        "sorted",
        "staticmethod",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "vars",
        "zip",
        "True",
        "False",
        "None",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "AttributeError",
        "ZeroDivisionError",
        "OverflowError",
        "ArithmeticError",
        "RuntimeError",
        # `__import__` is needed for `import` statements to work; the
        # MetaPathFinder gates which modules can actually be imported.
        # `__build_class__` is needed for `class Foo: ...` syntax.
        # `open`/`exec`/`eval`/`compile`/`input`/`exit`/`quit`/`breakpoint`/
        # `help` are intentionally absent.
        "__import__",
        "__build_class__",
    }
    return {name: getattr(builtins, name) for name in safe if hasattr(builtins, name)}


def _decode_images(payloads: dict[str, bytes], pil_image_module) -> dict:
    """Turn raw PNG bytes into PIL.Image objects, keyed by the original ref."""
    if pil_image_module is None:
        return {}
    out = {}
    for ref, data in payloads.items():
        try:
            img = pil_image_module.open(BytesIO(data))
            img.load()  # Force decode now.
            out[ref] = img
        except Exception:
            continue
    return out


def _make_save_image(pil_image_module):
    """Return a `save_image(img)` helper that appends to _new_images_buffer."""

    def save_image(img) -> None:
        if pil_image_module is None or img is None:
            return
        buf = BytesIO()
        img.save(buf, format="PNG")
        # Look up the buffer in the caller's frame so we don't need globals.
        import sys as _sys

        frame = _sys._getframe(1)
        ns = frame.f_globals
        ns.setdefault("_new_images_buffer", []).append(buf.getvalue())

    return save_image


class _FdWriter:
    """Minimal stream wrapper that writes to a BytesIO buffer."""

    def __init__(self, buf: BytesIO) -> None:
        self._buf = buf

    def write(self, s) -> int:
        if isinstance(s, str):
            s = s.encode("utf-8", errors="replace")
        return self._buf.write(s)

    def flush(self) -> None:
        pass
