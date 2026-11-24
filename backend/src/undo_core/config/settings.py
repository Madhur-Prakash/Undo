"""Typed, validated settings persisted as JSON in the data directory."""

from __future__ import annotations

import ipaddress
import json
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from undo_core.config import defaults as d
from undo_core.utils.atomic import atomic_write_text
from undo_core.utils.errors import InvalidInputError
from undo_core.utils.sizes import parse_size


class _Section(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class CompressionSettings(_Section):
    enabled: bool = True
    level: int = Field(d.DEFAULT_COMPRESSION_LEVEL, ge=1, le=22)
    min_size: int = Field(64, ge=0, description="Files smaller than this are stored raw.")
    skip_extensions: list[str] = Field(default_factory=lambda: list(d.INCOMPRESSIBLE_EXTENSIONS))

    @field_validator("skip_extensions")
    @classmethod
    def _norm_ext(cls, value: list[str]) -> list[str]:
        return sorted({(e if e.startswith(".") else f".{e}").lower() for e in value if e})


class ChunkingSettings(_Section):
    enabled: bool = False
    chunk_size: int = Field(d.DEFAULT_CHUNK_SIZE, ge=64 * d.KIB, le=256 * d.MIB)
    min_file_size: int = Field(
        16 * d.MIB, ge=0, description="Only files at least this big are chunked."
    )


class CaptureSettings(_Section):
    max_file_size: int = Field(d.DEFAULT_MAX_FILE_SIZE, ge=0)
    debounce_seconds: float = Field(1.0, ge=0, le=600)
    stable_seconds: float = Field(0.5, ge=0, le=600)
    retry_seconds: float = Field(2.0, ge=0, le=3600)
    max_retries: int = Field(5, ge=0, le=100)
    max_concurrent: int = Field(2, ge=1, le=64)


class MonitorSettings(_Section):
    reconcile_interval_seconds: int = Field(3600, ge=30)
    initial_scan: bool = True
    force_polling: bool = False
    polling_interval_seconds: float = Field(10.0, ge=0.5)
    event_queue_size: int = Field(10_000, ge=100, le=1_000_000)
    follow_symlinks: bool = False
    exclude_hidden: bool = False


class RetentionSettings(_Section):
    keep_all: bool = True
    keep_last: int | None = Field(None, ge=1)
    keep_days: int | None = Field(None, ge=1)
    daily_days: int | None = Field(None, ge=1)
    weekly_weeks: int | None = Field(None, ge=1)
    max_storage_bytes: int | None = Field(None, ge=0)
    interval_seconds: int = Field(86_400, ge=60)


class ExclusionSettings(_Section):
    defaults: list[str] = Field(default_factory=lambda: list(d.DEFAULT_EXCLUSIONS))


class ApiSettings(_Section):
    host: str = d.DEFAULT_API_HOST
    port: int = Field(d.DEFAULT_API_PORT, ge=0, le=65535)
    allow_remote: bool = False

    @model_validator(mode="after")
    def _loopback_only(self) -> ApiSettings:
        if not self.allow_remote:
            try:
                is_loop = ipaddress.ip_address(self.host).is_loopback
            except ValueError:
                is_loop = self.host == "localhost"
            if not is_loop:
                raise ValueError(
                    "api.host must be a loopback address unless api.allow_remote is true"
                )
        return self


class DaemonSettings(_Section):
    autostart: bool = Field(
        True,
        description="Clients (desktop GUI, TUI) start the daemon automatically when it is not running.",
    )
    gc_interval_seconds: int = Field(86_400, ge=300)
    gc_grace_seconds: int = Field(3600, ge=0)
    verify_interval_seconds: int = Field(0, ge=0, description="0 disables scheduled verification.")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class UiSettings(_Section):
    theme: Literal["system", "light", "dark"] = "system"


class Settings(_Section):
    compression: CompressionSettings = Field(default_factory=CompressionSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    capture: CaptureSettings = Field(default_factory=CaptureSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    exclusions: ExclusionSettings = Field(default_factory=ExclusionSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    daemon: DaemonSettings = Field(default_factory=DaemonSettings)
    ui: UiSettings = Field(default_factory=UiSettings)


_SIZE_KEYS = {
    "capture.max_file_size",
    "chunking.chunk_size",
    "chunking.min_file_size",
    "compression.min_size",
    "retention.max_storage_bytes",
}


def _coerce(key: str, raw: Any) -> Any:
    """Convert CLI string input into JSON-compatible values before validation."""
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if text.lower() in ("none", "null", ""):
        return None
    if key in _SIZE_KEYS:
        return parse_size(text)
    if text.lower() in ("true", "yes", "on"):
        return True
    if text.lower() in ("false", "no", "off"):
        return False
    if text.startswith("[") or text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"Invalid JSON value for {key}: {exc}") from exc
    if key in ("exclusions.defaults", "compression.skip_extensions"):
        return [p.strip() for p in text.split(",") if p.strip()]
    return text


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    else:
        out[prefix] = value


class SettingsStore:
    """Loads, validates and atomically persists :class:`Settings`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._settings = self._load()
        self._mtime = self._stat_mtime()

    def _stat_mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    def _load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return Settings.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise InvalidInputError(f"Invalid settings file {self.path}: {exc}") from exc

    @property
    def current(self) -> Settings:
        """Current settings; reloads if another process changed the file."""
        with self._lock:
            mtime = self._stat_mtime()
            if mtime and mtime != self._mtime:
                try:
                    self._settings = self._load()
                    self._mtime = mtime
                except InvalidInputError:
                    pass
            return self._settings

    def save(self, settings: Settings | None = None) -> None:
        with self._lock:
            if settings is not None:
                self._settings = settings
            atomic_write_text(self.path, self._settings.model_dump_json(indent=2))
            self._mtime = self._stat_mtime()

    def as_dict(self) -> dict[str, Any]:
        return self.current.model_dump(mode="json")

    def flat(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        _flatten("", self.as_dict(), out)
        return out

    def get_value(self, key: str) -> Any:
        flat = self.flat()
        if key in flat:
            return flat[key]
        section = self.as_dict().get(key)
        if section is None:
            raise InvalidInputError(f"Unknown setting {key!r}")
        return section

    def set_value(self, key: str, raw: Any) -> Settings:
        """Set a dotted key (``capture.max_file_size``) from user input and persist."""
        parts = key.split(".")
        if len(parts) != 2:
            raise InvalidInputError(
                "Setting keys have the form section.name, e.g. compression.level"
            )
        section, name = parts
        data = self.as_dict()
        if section not in data or name not in data[section]:
            raise InvalidInputError(f"Unknown setting {key!r}")
        data[section][name] = _coerce(key, raw)
        return self.update(data)

    def update(self, data: dict[str, Any]) -> Settings:
        """Deep-merge a (partial) dict and persist after validation."""
        merged = self.as_dict()
        for section, values in data.items():
            if section not in merged:
                raise InvalidInputError(f"Unknown settings section {section!r}")
            if not isinstance(values, dict):
                raise InvalidInputError(f"Settings section {section!r} must be an object")
            for name, value in values.items():
                if name not in merged[section]:
                    raise InvalidInputError(f"Unknown setting {section}.{name}")
                merged[section][name] = _coerce(f"{section}.{name}", value)
        try:
            new = Settings.model_validate(merged)
        except ValidationError as exc:
            msgs = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            raise InvalidInputError(f"Invalid settings: {msgs}") from exc
        self.save(new)
        return new
