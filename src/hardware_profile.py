"""Redacted hardware / environment profiler for the acoustic PoC."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class HardwareProfile:
    os: str
    python_version: str
    git_commit: str
    audio_backend: str
    host_apis: List[str] = field(default_factory=list)
    input_devices: List[Dict[str, Any]] = field(default_factory=list)
    output_devices: List[Dict[str, Any]] = field(default_factory=list)
    default_input: Optional[int] = None
    default_output: Optional[int] = None
    pipewire: bool = False
    pulseaudio: bool = False
    alsa: bool = False
    capture_nonzero: Optional[bool] = None
    playback_open_ok: Optional[bool] = None
    clipping_during_test: Optional[bool] = None
    notes: List[str] = field(default_factory=list)


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def collect_profile(
    *,
    probe_audio: bool = True,
    redacted: bool = True,
    input_device: Optional[int] = None,
    output_device: Optional[int] = None,
) -> HardwareProfile:
    profile = HardwareProfile(
        os=f"{platform.system()} {platform.release()}",
        python_version=platform.python_version(),
        git_commit=_git_commit(),
        audio_backend="sounddevice/PortAudio",
        pipewire=shutil.which("pw-cli") is not None or Path("/usr/bin/pipewire").exists(),
        pulseaudio=shutil.which("pactl") is not None,
        alsa=shutil.which("arecord") is not None,
    )
    try:
        import sounddevice as sd

        hostapis = sd.query_hostapis()
        if isinstance(hostapis, tuple):
            profile.host_apis = [str(h.get("name")) for h in hostapis]
        else:
            profile.host_apis = [str(hostapis.get("name"))]
        devices = sd.query_devices()
        defaults = sd.default.device
        if isinstance(defaults, (list, tuple)) and len(defaults) >= 2:
            profile.default_input = int(defaults[0]) if defaults[0] is not None else None
            profile.default_output = int(defaults[1]) if defaults[1] is not None else None
        for i, d in enumerate(devices):
            name = str(d["name"])
            if redacted:
                # Keep generic class, strip overly specific serial-like tokens
                name = name.split(":")[0].strip()
            entry = {
                "index": i,
                "name": name,
                "max_input_channels": int(d["max_input_channels"]),
                "max_output_channels": int(d["max_output_channels"]),
                "default_samplerate": float(d["default_samplerate"]),
            }
            if entry["max_input_channels"] > 0:
                profile.input_devices.append(entry)
            if entry["max_output_channels"] > 0:
                profile.output_devices.append(entry)
        if probe_audio:
            in_dev = input_device if input_device is not None else profile.default_input
            out_dev = output_device if output_device is not None else profile.default_output
            # Capture probe
            try:
                rec = sd.rec(
                    int(0.5 * 48000),
                    samplerate=48000,
                    channels=1,
                    dtype="float32",
                    device=in_dev,
                )
                sd.wait()
                x = np.asarray(rec, dtype=np.float64).reshape(-1)
                profile.capture_nonzero = bool(np.max(np.abs(x)) > 1e-5)
                profile.clipping_during_test = bool(np.any(np.abs(x) >= 0.98))
            except Exception as exc:
                profile.notes.append(f"capture probe failed: {exc}")
                profile.capture_nonzero = False
            # Playback open probe (silent buffer)
            try:
                sd.play(np.zeros(4800, dtype=np.float32), samplerate=48000, device=out_dev)
                time.sleep(0.05)
                sd.stop()
                profile.playback_open_ok = True
            except Exception as exc:
                profile.notes.append(f"playback probe failed: {exc}")
                profile.playback_open_ok = False
    except Exception as exc:
        profile.notes.append(f"sounddevice unavailable: {exc}")
    return profile


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.hardware_profile")
    parser.add_argument("--redacted", action="store_true", default=True)
    parser.add_argument("--no-redacted", action="store_false", dest="redacted")
    parser.add_argument("--no-probe", action="store_true")
    parser.add_argument("--input-device", type=int, default=None)
    parser.add_argument("--output-device", type=int, default=None)
    parser.add_argument(
        "--json-out", type=Path, default=Path("output/hardware-profile.json")
    )
    parser.add_argument(
        "--txt-out", type=Path, default=Path("output/hardware-profile.txt")
    )
    args = parser.parse_args(argv)
    profile = collect_profile(
        probe_audio=not args.no_probe,
        redacted=args.redacted,
        input_device=args.input_device,
        output_device=args.output_device,
    )
    data = asdict(profile)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(data, indent=2))
    lines = [
        f"OS: {profile.os}",
        f"Python: {profile.python_version}",
        f"Git: {profile.git_commit}",
        f"Backend: {profile.audio_backend}",
        f"Host APIs: {', '.join(profile.host_apis)}",
        f"PipeWire={profile.pipewire} Pulse={profile.pulseaudio} ALSA={profile.alsa}",
        f"Default in/out: {profile.default_input}/{profile.default_output}",
        f"Capture nonzero: {profile.capture_nonzero}",
        f"Playback open OK: {profile.playback_open_ok}",
        f"Clipping during test: {profile.clipping_during_test}",
        "Inputs:",
    ]
    for d in profile.input_devices:
        lines.append(f"  [{d['index']}] {d['name']} in={d['max_input_channels']} sr={d['default_samplerate']}")
    lines.append("Outputs:")
    for d in profile.output_devices:
        lines.append(f"  [{d['index']}] {d['name']} out={d['max_output_channels']} sr={d['default_samplerate']}")
    for n in profile.notes:
        lines.append(f"NOTE: {n}")
    text = "\n".join(lines) + "\n"
    args.txt_out.write_text(text)
    print(text)
    print(f"Wrote {args.json_out} and {args.txt_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
