"""Local, rolling diagnostics history for one Bridge entry."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from hashlib import blake2s
import json
import logging
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryFile
import time
from typing import Any, BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile
import zlib

_LOGGER = logging.getLogger(__name__)
RETENTION_HOURS = 24
RETENTION_SECONDS = RETENTION_HOURS * 60 * 60
MAX_PENDING = 512
_FILE_PREFIX = "alphaess_api_history_"
STREAM_FILES = {
    "api": "api-verlauf.jsonl",
    "bridge": "bridge-verlauf.jsonl",
    "control": "steuerung.jsonl",
}
_SECRET = re.compile(r"password|passwd|token|auth|secret|credential|cookie|api.?key|private.?key", re.I)
_PRIVATE = re.compile(
    r"^(id|sn|uuid|deviceid|userid|accountid|sessionid|macaddress|ip|lat|lng|lon)$"
    r"|sn$|serial|email|phone|mobile|address|username|latitude|longitude"
    r"|location|postalcode|zipcode|sitename|systemname|ownername|installername",
    re.I,
)
_PRIVATE_TEXT = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[\w.+/=\-]+|\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b"
    r"|\beyJ[\w-]+\.[\w-]+\.[\w-]+\b"
)


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def _timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class ApiHistory:
    """Buffer briefly in memory, write and export off the Home Assistant loop."""

    def __init__(self, hass, entry_id: str, enabled: bool, identifiers: tuple[str, ...], password: str = "") -> None:
        self.hass = hass
        self.enabled = enabled
        self.path = Path(hass.config.path(".storage", f"{_FILE_PREFIX}{entry_id}.sqlite3"))
        self._key = entry_id.encode()
        self._password = password
        self._identifiers = {s: self._alias(s) for s in identifiers if isinstance(s, str) and s}
        self._pending: deque[tuple[float, str, dict]] = deque(maxlen=MAX_PENDING)
        self._dropped = 0
        self._lock = asyncio.Lock()
        self._closed = False
        self._storage_error = False

    def _alias(self, value: Any) -> str:
        return "id-" + blake2s(str(value).encode(), key=self._key, digest_size=8).hexdigest()

    def add_identifier(self, value: Any) -> None:
        if isinstance(value, str) and value and value not in self._identifiers:
            self._identifiers[value] = self._alias(value)

    def _clean(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                if _SECRET.search(key):
                    continue
                safe_key = self._clean(key)
                cleaned[safe_key] = (
                    self._alias(item) if _PRIVATE.search(key) and item is not None
                    else self._clean(item)
                )
            return cleaned
        if isinstance(value, list):
            return [self._clean(item) for item in value]
        if isinstance(value, str):
            if self._password and (value == self._password or len(self._password) >= 8):
                value = value.replace(self._password, "[redacted]")
            for identifier, alias in self._identifiers.items():
                if value == identifier or len(identifier) >= 5:
                    value = value.replace(identifier, alias)
            return _PRIVATE_TEXT.sub("[redacted]", value)
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return str(value)
        return value

    def record(self, stream: str, **event: Any) -> None:
        """Take a sanitized copy before data is processed or queued for disk."""
        if not self.enabled or self._closed:
            return
        try:
            cleaned = self._clean(event)
        except (ValueError, TypeError, RecursionError):
            self._dropped += 1
            return
        if len(self._pending) == MAX_PENDING:
            self._dropped += 1
        self._pending.append((time.time(), stream, cleaned))

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            self.path.touch(mode=0o600, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS history "
                "(id INTEGER PRIMARY KEY, at REAL NOT NULL, stream TEXT NOT NULL, data BLOB NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS history_at ON history(at)")
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    def _write(self, batch, cutoff: float) -> None:
        if not batch and not self.path.exists():
            return
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM history WHERE at < ?", (cutoff,))
            connection.executemany(
                "INSERT INTO history(at, stream, data) VALUES (?, ?, ?)",
                ((at, stream, zlib.compress(_json({"at": _timestamp(at), **event})))
                 for at, stream, event in batch if at >= cutoff),
            )

    async def async_flush(self, _event=None) -> None:
        async with self._lock:
            batch = list(self._pending)
            self._pending.clear()
            dropped, self._dropped = self._dropped, 0
            if dropped:
                batch.append((time.time(), "bridge", {"event": "recording_gap", "dropped": dropped}))
            try:
                await self.hass.async_add_executor_job(self._write, batch, time.time() - RETENTION_SECONDS)
                self._storage_error = False
            except (OSError, sqlite3.Error, ValueError, TypeError):
                # A broken storage device must not interfere with charging or polling.
                if not self._storage_error:
                    _LOGGER.warning("Could not write local AlphaESS API diagnostics history")
                self._storage_error = True
                queued = batch + list(self._pending)
                self._dropped += max(0, len(queued) - MAX_PENDING)
                self._pending = deque(queued[-MAX_PENDING:], maxlen=MAX_PENDING)

    async def async_close(self, _event=None) -> None:
        if not self._closed:
            self.record("bridge", event="recording_stopped")
            self._closed = True
        await self.async_flush()

    def _build_zip(self, summary: dict, snapshot: dict, cutoff: float) -> BinaryIO:
        output = TemporaryFile()
        try:
            counts = dict.fromkeys(STREAM_FILES, 0)
            first = last = None
            with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=3) as archive:
                if self.path.exists():
                    with closing(self._connect()) as connection, connection:
                        connection.execute("BEGIN")
                        for stream, filename in STREAM_FILES.items():
                            with archive.open(filename, "w", force_zip64=True) as part:
                                for at, blob in connection.execute(
                                    "SELECT at, data FROM history WHERE at >= ? AND stream = ? ORDER BY at, id",
                                    (cutoff, stream),
                                ):
                                    first = at if first is None else min(first, at)
                                    last = at if last is None else max(last, at)
                                    counts[stream] += 1
                                    part.write(zlib.decompress(blob) + b"\n")
                else:
                    for filename in STREAM_FILES.values():
                        archive.writestr(filename, b"")
                summary["api_history"] = {
                    "enabled": self.enabled,
                    "retention_hours": RETENTION_HOURS,
                    "from": _timestamp(first) if first is not None else None,
                    "to": _timestamp(last) if last is not None else None,
                    "records": counts,
                    "storage_error": self._storage_error,
                }
                manifest = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))
                summary["bridge_manifest_version"] = manifest["version"]
                archive.writestr("diagnose.json", _json(summary))
                if not counts["api"]:
                    archive.writestr("api-momentaufnahme.json", _json(snapshot))
            output.seek(0)
            return output
        except BaseException:
            output.close()
            raise

    async def async_export(self, summary: dict, snapshot: dict) -> BinaryIO:
        await self.async_flush()
        return await self.hass.async_add_executor_job(
            self._build_zip, self._clean(summary), self._clean(snapshot), time.time() - RETENTION_SECONDS
        )


def purge_expired_archives(storage: str) -> None:
    """Also expire files belonging to entries that are currently disabled."""
    cutoff = time.time() - RETENTION_SECONDS
    for path in Path(storage).glob(f"{_FILE_PREFIX}*.sqlite3"):
        if path.is_symlink():
            continue
        try:
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("PRAGMA secure_delete = ON")
                connection.execute("DELETE FROM history WHERE at < ?", (cutoff,))
        except sqlite3.Error:
            _LOGGER.debug("Could not prune an AlphaESS API diagnostics archive")


def remove_archive(storage: str, entry_id: str) -> None:
    """Remove the archive for a deleted config entry."""
    path = Path(storage) / f"{_FILE_PREFIX}{entry_id}.sqlite3"
    for suffix in ("", "-wal", "-shm", "-journal"):
        (path.parent / (path.name + suffix)).unlink(missing_ok=True)
