"""Router configuration (TOML, stdlib tomllib only)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class RouterConfig:
    routing_enabled: bool = True
    capture_mode: str = "review"  # review | auto
    timeout_ms: int = 30_000
    jev_model: str = "jev-latest"
    credential_ref: str = ""  # env var name or op:// path; never a literal key
    skill_dirs: list[str] = field(default_factory=list)
    vault_rules: list[str] = field(default_factory=list)
    brain_vaults: list[str] = field(default_factory=list)
    roster_path: str = ""
    state_dir: str = "~/.local/state/router"

    @classmethod
    def load(cls, path: Path | str) -> "RouterConfig":
        path = Path(path).expanduser()
        if not path.is_file():
            raise ConfigError(f"config not found: {path}")
        try:
            raw = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"invalid TOML in {path}: {e}") from e
        cfg = cls()
        top = {k: v for k, v in raw.items() if hasattr(cfg, k)}
        for k, v in top.items():
            setattr(cfg, k, v)
        sources = raw.get("sources", {})
        cfg.skill_dirs = list(sources.get("skill_dirs", cfg.skill_dirs))
        cfg.vault_rules = list(sources.get("vault_rules", cfg.vault_rules))
        cfg.brain_vaults = list(sources.get("brain_vaults", cfg.brain_vaults))
        cfg.roster_path = str(sources.get("roster_path", cfg.roster_path))
        if cfg.capture_mode not in ("review", "auto"):
            raise ConfigError(f"capture_mode must be review|auto, got {cfg.capture_mode!r}")
        return cfg

    def state_path(self, *parts: str) -> Path:
        p = Path(self.state_dir).expanduser()
        for part in parts:
            p = p / part
        return p
