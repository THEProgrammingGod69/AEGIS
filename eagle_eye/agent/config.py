"""Settings of the Claude vision agent: environment variables, model ids, prices and limits.

Everything is read at call time (``load()``), not at import time, so a server picks up a key added to its environment
and tests can monkeypatch variables. Engine-wide paths come from the top-level ``config`` module.
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

import config as engine_config

DEFAULT_MODEL = "claude-opus-5-5"
AUTO_PREFERENCE = ("claude-fable-5-1", "claude-opus-5-5")     # EAGLE_AGENT_MODEL=auto: first one the key can use
# Models whose policy declines are re-run server side with `fallbacks: "default"` (beta header below).
FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
PROMPT_VERSION = "eagle-agent/1"         # part of every cache key: bump when prompts or tools change meaning

# USD per million tokens: (input, output, cache read, cache write with the 5-minute TTL); list prices, Oct 2026.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-8": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
UNKNOWN_PRICE = PRICES["claude-fable-5-1"]    # unknown model: priced at the top tier so the cost is an upper bound


@dataclass(frozen=True)
class Settings:
    enabled: object            # None (auto), True or False - EAGLE_AGENT_ENABLED
    backend: str               # auto | anthropic | replay | mock
    model: str                 # main model id or "auto"
    fast_model: str            # bulk per-finding model
    effort: str
    fast_effort: str
    max_calls: int             # API requests per photo
    max_turns: int             # tool turns per finding
    max_tokens: int            # per request (thinking included)
    token_budget: int          # uncached input + cache writes + output per photo
    timeout: float
    parallel: int
    replay: object             # path or None
    record: object             # path or None
    fallbacks: bool
    overview: bool
    overview_min: int
    escalate: bool
    cache: bool
    cache_dir: Path
    image_max: int             # longest side of any image sent
    drawing_tiles: int


def _env(name, default=None):
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


def _int(name, default, lo, hi):
    try:
        return max(lo, min(hi, int(float(_env(name, default)))))
    except ValueError:
        return default


def _flag(name, default):
    v = _env(name)
    if v is None:
        return default
    return v.lower() not in ("0", "false", "no", "off")


def _effort(name, default):
    v = (_env(name) or default).lower()
    return v if v in EFFORTS else default


def load():
    """Current settings from the environment."""
    enabled = _env("EAGLE_AGENT_ENABLED")
    try:
        timeout = max(5.0, float(_env("EAGLE_AGENT_TIMEOUT", 60)))
    except ValueError:
        timeout = 60.0
    return Settings(
        enabled=None if enabled is None else _flag("EAGLE_AGENT_ENABLED", True),
        backend=(_env("EAGLE_AGENT_BACKEND") or "auto").lower(),
        model=_env("EAGLE_AGENT_MODEL", "auto"),
        fast_model=_env("EAGLE_AGENT_FAST_MODEL", DEFAULT_MODEL),
        effort=_effort("EAGLE_AGENT_EFFORT", "high"),
        fast_effort=_effort("EAGLE_AGENT_FAST_EFFORT", "medium"),
        max_calls=_int("EAGLE_AGENT_MAX_CALLS", 25, 0, 1000),
        max_turns=_int("EAGLE_AGENT_MAX_TURNS", 4, 1, 12),
        max_tokens=_int("EAGLE_AGENT_MAX_TOKENS", 16000, 1024, 64000),
        token_budget=_int("EAGLE_AGENT_TOKEN_BUDGET", 600_000, 1000, 50_000_000),
        timeout=timeout,
        parallel=_int("EAGLE_AGENT_PARALLEL", 4, 1, 16),
        replay=_env("EAGLE_AGENT_REPLAY"),
        record=_env("EAGLE_AGENT_RECORD"),
        fallbacks=_flag("EAGLE_AGENT_FALLBACKS", True),
        overview=_flag("EAGLE_AGENT_OVERVIEW", True),
        overview_min=_int("EAGLE_AGENT_OVERVIEW_MIN", 3, 1, 1000),
        escalate=_flag("EAGLE_AGENT_ESCALATE", True),
        cache=_flag("EAGLE_AGENT_CACHE", True),
        cache_dir=Path(_env("EAGLE_AGENT_CACHE_DIR") or engine_config.DATA / "cache" / "agent"),
        image_max=_int("EAGLE_AGENT_IMAGE_MAX", 1568, 256, 2576),
        drawing_tiles=_int("EAGLE_AGENT_DRAWING_TILES", 6, 1, 16),
    )


def has_credentials():
    """True when an API key or auth token is in the environment (ANTHROPIC_BASE_URL alone does not count)."""
    return bool(_env("ANTHROPIC_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN"))


def price(model):
    return PRICES.get(model, UNKNOWN_PRICE)


def cost_usd(usage, model):
    """Dollar cost of one request's usage dict {input, output, cache_read, cache_write}."""
    p_in, p_out, p_read, p_write = price(model)
    return (usage.get("input", 0) * p_in + usage.get("output", 0) * p_out + usage.get("cache_read", 0) * p_read
            + usage.get("cache_write", 0) * p_write) / 1e6


_SECRET_RX = [re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}")]


def redact(text):
    """Remove API keys / tokens from text that is logged or stored."""
    if not isinstance(text, str) or not text:
        return text
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        secret = os.environ.get(name) or ""
        if len(secret.strip()) >= 8:
            text = text.replace(secret.strip(), "[REDACTED]")
    text = _SECRET_RX[0].sub("sk-ant-[REDACTED]", text)
    return _SECRET_RX[1].sub(r"\1[REDACTED]", text)
