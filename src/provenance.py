"""Provenance labels and fail-closed physical-capture metadata validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


SCHEMA_VERSION: str = "1.0"


class Provenance(str, Enum):
    GENERATED_TX = "GENERATED_TX"
    SIMULATED_RX = "SIMULATED_RX"
    PHYSICAL_RX = "PHYSICAL_RX"
    PHYSICAL_REPLAY = "PHYSICAL_REPLAY"
    UNKNOWN = "UNKNOWN"

    def plot_title(self, base: str) -> str:
        return f"{base} [{self.value}]"


class ProvenanceError(ValueError):
    """Raised when capture metadata fails validation."""


MANDATORY_PHYSICAL_FIELDS: tuple[str, ...] = (
    "schema_version",
    "provenance",
    "timestamp",
    "git_commit",
    "wav_sha256",
    "sample_rate",
    "frequency_zero_hz",
    "frequency_one_hz",
    "symbol_duration_seconds",
    "modulation",
    "fec_mode",
    "sync_mode",
    "payload_length",
)


@dataclass(frozen=True)
class CaptureMetadata:
    """Validated metadata for a physical capture used in replay."""

    schema_version: str
    provenance: str
    timestamp: str
    git_commit: str
    wav_sha256: str
    sample_rate: int
    frequency_zero_hz: float
    frequency_one_hz: float
    symbol_duration_seconds: float
    modulation: str
    fec_mode: str
    sync_mode: str
    payload_length: int
    expected_payload: Optional[str] = None
    frequency_search_hz: float = 0.0
    frequency_search_step_hz: float = 10.0
    filter_enabled: bool = True
    amplitude: Optional[float] = None
    notes: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        extra = d.pop("extra", {}) or {}
        d.update(extra)
        return d


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_metadata_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProvenanceError(f"Missing metadata file: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"Corrupt metadata JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProvenanceError("Metadata root must be a JSON object")
    return data


def validate_physical_metadata(
    meta: Mapping[str, Any],
    *,
    wav_path: Optional[Path] = None,
    require_hash_match: bool = True,
) -> CaptureMetadata:
    """Fail-closed validation for PHYSICAL_RX replay metadata."""
    missing = [k for k in MANDATORY_PHYSICAL_FIELDS if k not in meta or meta[k] in (None, "")]
    if missing:
        raise ProvenanceError(f"Missing mandatory metadata fields: {', '.join(missing)}")

    prov = str(meta["provenance"])
    if prov == Provenance.UNKNOWN.value:
        raise ProvenanceError("provenance UNKNOWN — reject physical replay")
    if prov not in (Provenance.PHYSICAL_RX.value, Provenance.PHYSICAL_REPLAY.value):
        raise ProvenanceError(
            f"Unsupported provenance for physical replay: {prov!r} "
            f"(expected PHYSICAL_RX or PHYSICAL_REPLAY)"
        )
    if str(meta["schema_version"]) != SCHEMA_VERSION:
        raise ProvenanceError(
            f"Unsupported schema_version {meta['schema_version']!r}; "
            f"expected {SCHEMA_VERSION!r}"
        )

    for key in (
        "modulation",
        "fec_mode",
        "sync_mode",
        "frequency_zero_hz",
        "frequency_one_hz",
        "symbol_duration_seconds",
        "sample_rate",
    ):
        if key not in meta or meta[key] in (None, ""):
            raise ProvenanceError(f"Missing mandatory field: {key}")

    wav_hash = str(meta["wav_sha256"]).lower().strip()
    if len(wav_hash) != 64 or any(c not in "0123456789abcdef" for c in wav_hash):
        raise ProvenanceError("wav_sha256 must be a 64-char hex SHA-256 digest")

    if wav_path is not None and require_hash_match:
        actual = sha256_file(wav_path)
        if actual.lower() != wav_hash:
            raise ProvenanceError(
                f"SHA-256 mismatch: metadata={wav_hash} actual={actual}"
            )

    known = set(MANDATORY_PHYSICAL_FIELDS) | {
        "expected_payload",
        "frequency_search_hz",
        "frequency_search_step_hz",
        "filter_enabled",
        "amplitude",
        "notes",
    }
    extra = {k: v for k, v in meta.items() if k not in known}
    return CaptureMetadata(
        schema_version=str(meta["schema_version"]),
        provenance=prov,
        timestamp=str(meta["timestamp"]),
        git_commit=str(meta["git_commit"]),
        wav_sha256=wav_hash,
        sample_rate=int(meta["sample_rate"]),
        frequency_zero_hz=float(meta["frequency_zero_hz"]),
        frequency_one_hz=float(meta["frequency_one_hz"]),
        symbol_duration_seconds=float(meta["symbol_duration_seconds"]),
        modulation=str(meta["modulation"]).lower(),
        fec_mode=str(meta["fec_mode"]).lower(),
        sync_mode=str(meta["sync_mode"]).lower(),
        payload_length=int(meta["payload_length"]),
        expected_payload=(
            str(meta["expected_payload"]) if meta.get("expected_payload") else None
        ),
        frequency_search_hz=float(meta.get("frequency_search_hz", 0.0)),
        frequency_search_step_hz=float(meta.get("frequency_search_step_hz", 10.0)),
        filter_enabled=bool(meta.get("filter_enabled", True)),
        amplitude=(float(meta["amplitude"]) if meta.get("amplitude") is not None else None),
        notes=str(meta.get("notes", "")),
        extra=extra,
    )


def write_physical_metadata(path: Path, meta: CaptureMetadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta.to_dict(), indent=2, sort_keys=True) + "\n")
