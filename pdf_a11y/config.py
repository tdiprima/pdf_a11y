"""Runtime configuration, sourced from environment variables with defaults."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# BCP 47 language tag, e.g. "en", "en-US", "es-419".
_LANG_PATTERN = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

DEFAULT_LANG = "en-US"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_WORKERS = 4
MAX_WORKERS = 32

# A file larger than this is skipped rather than risking memory exhaustion on
# a batch host. Override with PDF_A11Y_MAX_FILE_MB.
DEFAULT_MAX_FILE_MB = 200


class ConfigError(ValueError):
    """Raised when configuration is present but invalid."""


@dataclass(frozen=True)
class Config:
    """Validated runtime settings."""

    lang: str = DEFAULT_LANG
    log_level: str = DEFAULT_LOG_LEVEL
    workers: int = DEFAULT_WORKERS
    max_file_mb: int = DEFAULT_MAX_FILE_MB

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read a bounded integer from the environment."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def validate_lang(lang: str) -> str:
    """Return the language tag if it is a plausible BCP 47 tag."""
    candidate = lang.strip()
    if not _LANG_PATTERN.match(candidate):
        raise ConfigError(f"language must be a BCP 47 tag such as en-US, got {lang!r}")
    return candidate


def load_config() -> Config:
    """Build configuration from the environment, validating every field."""
    lang = validate_lang(os.environ.get("PDF_A11Y_LANG", DEFAULT_LANG))

    log_level = os.environ.get("PDF_A11Y_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    if log_level not in _VALID_LOG_LEVELS:
        raise ConfigError(
            f"PDF_A11Y_LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got {log_level!r}"
        )

    return Config(
        lang=lang,
        log_level=log_level,
        workers=_read_int("PDF_A11Y_WORKERS", DEFAULT_WORKERS, 1, MAX_WORKERS),
        max_file_mb=_read_int("PDF_A11Y_MAX_FILE_MB", DEFAULT_MAX_FILE_MB, 1, 10_000),
    )
