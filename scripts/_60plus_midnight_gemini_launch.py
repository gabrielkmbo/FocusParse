"""Wait for Gemini quota reset, then launch the full Phase 3a v2 + 3d + 3b stack on n=148.

Polls `gemini-2.5-flash` every 5 minutes (5 sequential probes per poll).
Launches the eval as soon as the cheap-tier quota recovers enough to
support sustained 296 calls (the full n=148 needs ~2 calls/example).

This is a one-shot launcher for the harness-60plus sprint. Stops when
the eval has been launched (the eval itself runs detached). Logs to
`logs/60plus-midnight-gemini-launch.log`.
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "logs/60plus-midnight-gemini-launch.log"
EVAL_LOG = REPO_ROOT / "logs/60plus-3a-3d-3b-gemini-midnight-run1.log"
OUTPUT_DIR = REPO_ROOT / "results/hf/sprint-2026-05-14/60plus-3a-3d-3b-gemini-midnight-run1"


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat()}] {msg}\n"
    LOG_PATH.parent.mkdir(exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line)
    print(line, end="", flush=True)


def load_env() -> dict[str, str]:
    env = os.environ.copy()
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def probe_gemini(env: dict[str, str], n: int = 5) -> int:
    """Return number of successful probes out of n."""
    for k, v in env.items():
        os.environ[k] = v
    import google.genai as genai

    client = genai.Client()
    ok = 0
    for i in range(n):
        try:
            client.models.generate_content(
                model="gemini-2.5-flash",
                contents="OK",
                config={"thinking_config": {"thinking_budget": 0}},
            )
            ok += 1
        except Exception as e:
            if "429" in str(e):
                return ok
    return ok


def launch_eval(env: dict[str, str]) -> int:
    """Launch the Gemini-cheap eval. Returns the PID."""
    if OUTPUT_DIR.exists():
        import shutil

        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_LOG.parent.mkdir(exist_ok=True)
    EVAL_LOG.write_text(
        f"Eval launched at {datetime.now().isoformat()}: "
        "Phase 3a v2 + 3d + 3b (k=2) on default Gemini cheap tier.\n"
    )

    with open(EVAL_LOG, "ab") as f:
        p = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "scripts/run_hf_eval.py",
                "--agent",
                "focus",
                "--protocol",
                "agentic_multi_page",
                "--tool-set",
                "full",
                "--chart-to-table",
                "--react-inspector",
                "--reasoner-self-consistency-k",
                "2",
                "--hf-split",
                "validation",
                "--output-dir",
                str(OUTPUT_DIR) + "/",
                "--no-resume",
            ],
            env=env,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=REPO_ROOT,
        )
    return p.pid


def main() -> int:
    env = load_env()
    log("Midnight-Gemini launcher started.")

    # Poll every 5 min, capped at 4 hours
    max_polls = 48
    for i in range(max_polls):
        ok = probe_gemini(env, n=5)
        log(f"Poll {i + 1}/{max_polls}: gemini-2.5-flash {ok}/5 successful")
        if ok >= 5:
            pid = launch_eval(env)
            log(f"Gemini quota recovered. Launched eval (PID {pid}).")
            log(f"  Output: {OUTPUT_DIR}")
            log(f"  Log:    {EVAL_LOG}")
            return 0
        log(f"  Not enough quota yet ({ok}/5). Sleeping 5 min.")
        time.sleep(300)

    log("ERROR: Gemini quota did not recover after 4 hours of polling.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
