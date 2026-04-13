"""run_python — sandboxed code execution for coding-driven zoom.

**This is the high-resolution zoom mechanism.** The model writes Python that
crops, super-samples (e.g. LANCZOS 2× on a 10-pixel-tall axis label), annotates,
or computes over prior crops, and the transformed output becomes a new virtual
image the model can re-inspect.

Security posture (research-grade, **not** production-isolation):
  - Runs in a subprocess, never `exec`/`eval` in-process.
  - `resource.setrlimit(CPU, 15)` + wall-time watchdog.
  - Import allowlist enforced via a sys.modules whitelist in the child.
  - No network syscalls permitted (child runs with env stripped of HTTP_PROXY /
    endpoint URLs; allowlist imports can't open sockets).
  - Tool input is code + content-addressed `image_refs`; the child only sees
    the actual bytes the parent resolves from the cache.

NEVER deploy FocusParse to accept untrusted questions — the sandbox is sufficient
for research, not adversarial defense.

TODO(Phase 3):
  - Implement `_run_child` with `multiprocessing.Process` + rlimit + allowlist.
  - Return stdout + optional new image (assigned a new content-addressed ref).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

ALLOWED_IMPORTS = {
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageEnhance",
    "PIL.ImageFilter",
    "PIL.ImageOps",
    "numpy",
    "matplotlib",
    "matplotlib.pyplot",
    "scipy",
    "scipy.ndimage",
    "scipy.signal",
    "io",
    "math",
    "statistics",
    "hashlib",
}

DEFAULT_WALL_TIME_S = 15
DEFAULT_CPU_S = 15
DEFAULT_RSS_MB = 1024


class RunPythonInput(BaseModel):
    code: str                                  # Python code the model wrote
    image_refs: list[str] = Field(default_factory=list)  # cache keys to make available
    wall_time_s: int = DEFAULT_WALL_TIME_S


class RunPythonOutput(BaseModel):
    stdout: str
    stderr: str = ""
    new_image_refs: list[str] = Field(default_factory=list)
    exit_code: int = 0
    timed_out: bool = False


async def run_python(inp: RunPythonInput) -> RunPythonOutput:
    raise NotImplementedError("run_python — wire in Phase 3 (subprocess + rlimit + allowlist)")
