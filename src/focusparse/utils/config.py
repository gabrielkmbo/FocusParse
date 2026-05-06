"""Load FocusParse config from YAML + environment overrides.

`configs/default.yaml` is the source of truth. Env vars named
`FOCUSPARSE_TIER_<ROLE>` (PLANNER|ROUTER|REASONER|VERIFIER|LOCALIZER_RERANK)
override the per-role tier assignment at runtime.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "configs" / "default.yaml"


class TierSpec(BaseModel):
    provider: str
    model: str
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    thinking_budget: int | None = None


class BudgetSpec(BaseModel):
    tokens: int = 120_000
    tool_calls: int = 12
    crops: int = 8
    max_turns: int = 10
    max_vlm_calls: int = 4


class EscalationSpec(BaseModel):
    confidence_threshold: float = 0.5
    max_steps_escalated_per_run: int = 1


class LayoutEndpointSpec(BaseModel):
    url: str
    rate_limit_rps: float = 2.0
    timeout_s: int = 180
    retries: int = 3


class DatasetSpec(BaseModel):
    source: str = "hf"                         # "hf" | "local"
    hf_repo: str = "gabrielbo/parser-bench"
    revision: str | None = None
    local_root: str | None = None


class NFSSpec(BaseModel):
    host: str = "llama-nfs"
    remote_root: str
    rsync_flags: list[str] = Field(default_factory=lambda: ["-a", "-z"])


class CacheSpec(BaseModel):
    root: str = "./cache"


class SFTFilter(BaseModel):
    min_coverage: float = 0.8
    min_iou: float = 0.3
    require_correct: bool = True


class TracesSpec(BaseModel):
    schema_version: str = "3"
    sft_filter: SFTFilter = Field(default_factory=SFTFilter)


class FocusConfig(BaseModel):
    tiers: dict[str, TierSpec]
    roles: dict[str, str]                      # role name -> tier name
    budget: BudgetSpec
    escalation: EscalationSpec
    endpoints: dict[str, LayoutEndpointSpec]
    dataset: DatasetSpec
    nfs: NFSSpec
    cache: CacheSpec
    traces: TracesSpec

    def tier_for(self, role: str) -> TierSpec:
        """Resolve the tier for a role, honoring FOCUSPARSE_TIER_<ROLE> env override."""
        env_key = f"FOCUSPARSE_TIER_{role.upper()}"
        tier_name = os.environ.get(env_key, self.roles.get(role))
        if tier_name is None:
            raise KeyError(f"No tier assigned for role={role!r} (and no {env_key} in env)")
        if tier_name not in self.tiers:
            raise KeyError(f"Tier {tier_name!r} (for role {role!r}) not in tiers config")
        return self.tiers[tier_name]


def load_config(path: Path | str | None = None) -> FocusConfig:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path) as f:
        raw: dict[str, Any] = yaml.safe_load(f)
    return FocusConfig.model_validate(raw)
