"""Local, rolling diagnostics history for one Bridge entry."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import blake2s
import json
import logging
from pathlib import Path
import re
from shutil import copyfileobj
import sqlite3
from tempfile import TemporaryFile
import time
from typing import Any, BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile
from uuid import uuid4
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
_RESPONSES_FILE = "api-antworten.jsonl"
_REDACTED = "[redacted]"
_SECRET = re.compile(
    r"password|passwd|token|auth|secret|credential|cookie|api.?key|private.?key|bearer"
    r"|^(check.?code|link.?man|refresh|session.?id)$",
    re.I,
)
_REMOVED_FIELDS = re.compile(
    r"^(?:installer(?:company|description|id|license|name|email|phone|.*address)"
    r"|(?:device|user|site)?(?:city|country(?:code|name|info)?|"
    r"state(?:name|code)?|province|region|street|postalcode|zipcode|address.*|location.*)"
    r"|(?:lan|wan|local|public|private|gateway)?ip(?:v[46]|address)?"
    r"|(?:wifi)?(?:ssid|bssid|pwd|passphrase)|mac(?:address)?"
    r"|siteid|installrecordid|installdate|installdatetime|(?:user|device|site)(?:description|remark)|realname|fullname)$",
    re.I,
)
_PRIVATE = re.compile(
    r"^(id|sn|uuid|deviceid|userid|accountid|sessionid|macaddress|ip|lat|lng|lon)$"
    r"|sn$|serial|email|phone|mobile|address|username|latitude|longitude"
    r"|location|postalcode|zipcode|sitename|systemname|ownername|installername|realname",
    re.I,
)
_PSEUDONYM = re.compile(r"id-[0-9a-f]{16}")
_PRIVATE_TEXT = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[\w.+/=\-]+|\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b"
    r"|\beyJ[\w-]+\.[\w-]+\.[\w-]+\b|\bsk-[A-Za-z0-9_-]+"
    r"|(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"
    r"|(?<![0-9a-f:])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f:])",
)


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def _timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def diagnostic_build() -> dict:
    """Identify shipped code without credentials or local repository metadata."""
    root = Path(__file__).parent
    try:
        version = json.loads((root / "manifest.json").read_text())["version"]
        digest = blake2s()
        for path in sorted(root.iterdir()):
            if path.suffix in {".py", ".js"} or path.name == "manifest.json":
                content = path.read_bytes()
                digest.update(path.name.encode() + b"\0" + len(content).to_bytes(8, "big") + content)
        return {"manifest_version": f"v{version}", "code_fingerprint": digest.hexdigest()[:16],
                "diagnostics_revision": 4}
    except (OSError, ValueError, KeyError):
        return {"diagnostics_revision": 4, "build_unavailable": True}


class ApiHistory:
    """Buffer briefly in memory, write and export off the Home Assistant loop."""

    def __init__(self, hass, entry_id: str, enabled: bool, identifiers: tuple[str, ...], password: str = "", *, build: dict | None = None) -> None:
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
        self.recording_context = {"recording_run": uuid4().hex,
                                  "started_at": _timestamp(time.time()), "build": build or {}}

    def _alias(self, value: Any) -> str:
        return "id-" + blake2s(str(value).encode(), key=self._key, digest_size=8).hexdigest()

    def add_identifier(self, value: Any) -> None:
        if isinstance(value, str) and value and value not in self._identifiers:
            # An export can be iterating over the previous identifiers in the executor.
            self._identifiers = {**self._identifiers, value: self._alias(value)}

    def _clean(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                # Preserve the operational schema while removing known private fields.
                if _REMOVED_FIELDS.fullmatch(re.sub(r"[_-]", "", key)):
                    continue
                safe_key = self._clean(key)
                if _SECRET.search(key):
                    cleaned[safe_key] = item if item is None or item == "" else _REDACTED
                elif _PRIVATE.search(key) and item is not None and item != "":
                    cleaned[safe_key] = (
                        item if isinstance(item, str) and _PSEUDONYM.fullmatch(item)
                        else self._alias(item)
                    )
                else:
                    cleaned[safe_key] = self._clean(item)
            return cleaned
        if isinstance(value, list):
            return [self._clean(item) for item in value]
        if isinstance(value, str):
            if self._password and (value == self._password or len(self._password) >= 8):
                value = value.replace(self._password, _REDACTED)
            for identifier, alias in self._identifiers.items():
                if value == identifier or len(identifier) >= 5:
                    value = value.replace(identifier, alias)
            return _PRIVATE_TEXT.sub(_REDACTED, value)
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return str(value)
        return value

    def record(self, stream: str, **event: Any) -> None:
        """Take a sanitized copy before data is processed or queued for disk."""
        if not self.enabled or self._closed:
            return
        try:
            cleaned = self._clean(event)
            cleaned["recording_run"] = self.recording_context["recording_run"]
            cleaned["build_fingerprint"] = self.recording_context["build"].get("code_fingerprint")
            if event.get("event") == "recording_started":
                cleaned["recording_context"] = self.recording_context
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

    @staticmethod
    def _collect_latest_exchange(exchanges: dict, at: float, event: dict) -> None:
        method, step = event.get("method"), event.get("step")
        if method not in ("GET", "POST", "PATCH") or not isinstance(step, str):
            return
        # The fixed step labels also cover supplemental reads with private URLs.
        exchange = exchanges.setdefault((method, step), {"method": method, "step": step})
        status = event.get("http_status")
        fields = ("http_status", "endpoint", "duration_ms", "response", "response_body",
                  "error", "stage")
        entry = {"at": _timestamp(at), **{key: event[key] for key in fields if key in event}}
        # A failed login can have an HTTP status but no response from this endpoint.
        if isinstance(status, int) and "stage" not in event:
            exchange["last_response"] = entry
        accepted = (200,) if method == "GET" else (200, 201, 204)
        if event.get("error") or (isinstance(status, int) and status not in accepted):
            exchange["last_error"] = entry

    def _build_zip(self, summary: dict, snapshot: dict, cutoff: float, progress) -> BinaryIO:
        @lru_cache(maxsize=32)
        def clean_response(encoded: bytes) -> tuple[Any, str]:
            body = self._clean(json.loads(encoded))
            return body, blake2s(_json(body)).hexdigest()

        report = progress or (lambda percent: None)
        report(10)
        output = TemporaryFile()
        try:
            counts = dict.fromkeys(STREAM_FILES, 0)
            first = last = None
            response_ids: set[str] = set()
            exchanges: dict[tuple[str, str], dict] = {}
            with (
                TemporaryFile() as responses,
                ZipFile(output, "w", ZIP_DEFLATED, compresslevel=6) as archive,
            ):
                if self.path.exists():
                    with closing(self._connect()) as connection, connection:
                        connection.execute("BEGIN")
                        total = connection.execute(
                            "SELECT COUNT(*) FROM history WHERE at >= ?", (cutoff,)
                        ).fetchone()[0]
                        processed, percent = 0, 10
                        for stream, filename in STREAM_FILES.items():
                            with archive.open(filename, "w", force_zip64=True) as part:
                                for at, blob in connection.execute(
                                    "SELECT at, data FROM history WHERE at >= ? AND stream = ? ORDER BY at, id",
                                    (cutoff, stream),
                                ):
                                    first = at if first is None else min(first, at)
                                    last = at if last is None else max(last, at)
                                    counts[stream] += 1
                                    # Apply the current filter to rows written before an update, too.
                                    raw = json.loads(zlib.decompress(blob))
                                    if stream == "api" and "response" in raw:
                                        body, response_id = clean_response(_json(raw.pop("response")))
                                        event = self._clean(raw)
                                        self._collect_latest_exchange(exchanges, at, {**event, "response": body})
                                        event["response_id"] = response_id
                                        if response_id not in response_ids:
                                            response_ids.add(response_id)
                                            responses.write(_json({"id": response_id, "response": body}) + b"\n")
                                    else:
                                        event = self._clean(raw)
                                        if stream in {"api", "control"}:
                                            self._collect_latest_exchange(exchanges, at, event)
                                    part.write(_json(event) + b"\n")
                                    processed += 1
                                    next_percent = 10 + 79 * processed // total
                                    if next_percent > percent:
                                        percent = next_percent
                                        report(percent)
                else:
                    for filename in STREAM_FILES.values():
                        archive.writestr(filename, b"")
                report(90)
                responses.seek(0)
                with archive.open(_RESPONSES_FILE, "w", force_zip64=True) as part:
                    copyfileobj(responses, part)
                report(95)
                summary["api_history"] = {
                    "archive_format": 2,
                    "enabled": self.enabled,
                    "retention_hours": RETENTION_HOURS,
                    "from": _timestamp(first) if first is not None else None,
                    "to": _timestamp(last) if last is not None else None,
                    "records": counts,
                    "unique_api_responses": len(response_ids),
                    "storage_error": self._storage_error,
                }
                summary["privacy"] = {
                    "mode": "filtered_api_payloads",
                    "contains_raw_api_responses": False,
                    "may_include_charge_history_values": True,
                }
                manifest = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))
                summary["bridge_manifest_version"] = manifest["version"]
                summary["recording_context"] = self.recording_context
                archive.writestr("diagnose.json", _json(summary))
                archive.writestr("api-uebersicht.json", _json({
                    "history_enabled": self.enabled,
                    "retention_hours": RETENTION_HOURS,
                    "endpoints": [exchanges[key] for key in sorted(exchanges)],
                }))
                if not counts["api"]:
                    archive.writestr("api-momentaufnahme.json", _json(self._clean(snapshot)))
            output.seek(0)
            report(99)
            return output
        except BaseException:
            output.close()
            raise

    async def async_export(self, summary: dict, snapshot: dict, progress=None) -> BinaryIO:
        await self.async_flush()
        loop = asyncio.get_running_loop()
        return await self.hass.async_add_executor_job(
            self._build_zip, self._clean(summary), snapshot, time.time() - RETENTION_SECONDS,
            (lambda percent: loop.call_soon_threadsafe(progress, percent)) if progress else None,
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
