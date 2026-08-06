#!/usr/bin/env python3
"""PHYSICAL_RX A/B bench: near-us-fast (this repo) vs ggwave ultrasound.

Requires: pip install ggwave; ACOUSTIC_REMOTE_TX / DIR / OUTPUT_DEVICE set.
Authorized lab only. Synthetic payloads only.

Usage:
  source configs/local-lab.env
  PYTHONPATH=. python scripts/part3/ggwave_physical_bench.py --trials 5
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]

# ggwave protocol IDs (upstream): 3=[U] Normal, 4=[U] Fast, 5=[U] Fastest
GGWAVE_ULTRASOUND_FASTEST = 5


@dataclass
class TrialResult:
    stack: str
    trial: int
    payload: str
    success: int
    recovered: str
    error: str
    airtime_s: float
    listen_s: float
    peak: float
    payload_goodput_bps: float
    wav: str
    provenance: str = "PHYSICAL_RX"


def _ensure_ggwave():
    try:
        import ggwave  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "ggwave Python package missing. Install with: "
            "pip install ggwave"
        ) from exc


def ggwave_encode_wav(payload: str, protocol_id: int, volume: int, path: Path) -> float:
    import ggwave

    raw = ggwave.encode(payload, protocolId=protocol_id, volume=volume)
    samples = np.frombuffer(raw, dtype=np.int16)
    # pad leading/trailing silence for capture / decoder markers
    pad = np.zeros(int(0.5 * 48000), dtype=np.int16)
    out = np.concatenate([pad, samples, pad])
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), 48000, out)
    return float(len(samples) / 48000.0)


def ggwave_decode_audio(audio: np.ndarray, sr: int = 48000) -> Tuple[Optional[str], str]:
    import ggwave

    ggwave.disableLog()
    if sr != 48000:
        # simple resample via linear (bench expects 48k capture)
        n = int(len(audio) * 48000 / sr)
        x = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(audio)), audio)
    else:
        x = audio
    x = np.asarray(x, dtype=np.float64)
    peak = np.max(np.abs(x)) or 1.0
    # avoid crushing quiet captures; scale to ~0.8 peak for int16
    scaled = (x / peak * 0.85 * 32767.0).astype(np.int16)
    raw = scaled.tobytes()
    params = ggwave.getDefaultParameters()
    inst = ggwave.init(params)
    try:
        for pid in range(9):
            ggwave.rxToggleProtocol(pid, 1)
        got: List[bytes] = []
        step = 2048 * 2
        for i in range(0, len(raw), step):
            r = ggwave.decode(inst, raw[i : i + step])
            if r:
                got.append(r)
        if not got:
            return None, "no_decode"
        # last successful decode
        text = got[-1].decode("utf-8", errors="replace")
        return text, ""
    finally:
        ggwave.free(inst)


def play_remote_wav(remote: str, rdir: str, outdev: int, local_wav: Path) -> None:
    remote_wav = f"/tmp/ggwave_bench_{local_wav.stem}.wav"
    subprocess.check_call(["scp", "-q", str(local_wav), f"{remote}:{remote_wav}"])
    # Tiny play helper on remote (avoid nested heredoc quoting issues)
    py = (
        "import sounddevice as sd; from scipy.io import wavfile; import numpy as np; "
        f"sr,x=wavfile.read({remote_wav!r}); x=np.asarray(x,dtype=np.float32); "
        "x=x.mean(1) if x.ndim>1 else x; "
        "peak=float(np.max(np.abs(x)) or 1.0); x=x/peak*0.30; "
        f"sd.play(x,sr,device={int(outdev)}); sd.wait(); print('PLAY_DONE')"
    )
    cmd = (
        f"cd {shlex.quote(rdir)} && . .venv/bin/activate && "
        f"PYTHONPATH=. python -c {shlex.quote(py)}"
    )
    subprocess.check_call(["ssh", remote, cmd])


def trial_ggwave(
    *,
    trial: int,
    payload: str,
    protocol_id: int,
    volume: int,
    remote: str,
    rdir: str,
    outdev: int,
    in_dev: int,
    out_dir: Path,
) -> TrialResult:
    import ggwave

    ggwave.disableLog()
    wav_tx = out_dir / f"ggwave_tx_p{protocol_id}_t{trial}.wav"
    air = ggwave_encode_wav(payload, protocol_id, volume, wav_tx)
    # Stage file on TX *before* capture so the listen window covers playback.
    remote_wav = f"/tmp/ggwave_bench_{wav_tx.stem}.wav"
    try:
        subprocess.check_call(["scp", "-q", str(wav_tx), f"{remote}:{remote_wav}"])
    except subprocess.CalledProcessError as exc:
        return TrialResult(
            stack=f"ggwave_ultrasound_p{protocol_id}",
            trial=trial,
            payload=payload,
            success=0,
            recovered="",
            error=f"scp_failed:{exc}",
            airtime_s=air,
            listen_s=0.0,
            peak=0.0,
            payload_goodput_bps=0.0,
            wav="",
        )

    listen = air + 4.0
    sr = 48000
    n = int(listen * sr)
    rec = sd.rec(n, samplerate=sr, channels=1, dtype="float32", device=in_dev)
    time.sleep(0.6)
    t0 = time.time()
    py = (
        "import sounddevice as sd; from scipy.io import wavfile; import numpy as np; "
        f"sr,x=wavfile.read({remote_wav!r}); x=np.asarray(x,dtype=np.float32); "
        "x=x.mean(1) if x.ndim>1 else x; "
        "peak=float(np.max(np.abs(x)) or 1.0); x=x/peak*0.30; "
        f"sd.play(x,sr,device={int(outdev)}); sd.wait(); print('PLAY_DONE')"
    )
    cmd = (
        f"cd {shlex.quote(rdir)} && . .venv/bin/activate && "
        f"PYTHONPATH=. python -c {shlex.quote(py)}"
    )
    try:
        subprocess.check_call(["ssh", remote, cmd])
    except subprocess.CalledProcessError as exc:
        sd.wait()
        return TrialResult(
            stack=f"ggwave_ultrasound_p{protocol_id}",
            trial=trial,
            payload=payload,
            success=0,
            recovered="",
            error=f"remote_play_failed:{exc}",
            airtime_s=air,
            listen_s=listen,
            peak=0.0,
            payload_goodput_bps=0.0,
            wav="",
        )
    sd.wait()
    elapsed = time.time() - t0
    audio = rec[:, 0].astype(np.float64)
    peak = float(np.max(np.abs(audio)))
    wav_rx = out_dir / f"ggwave_rx_p{protocol_id}_t{trial}.wav"
    wavfile.write(str(wav_rx), sr, audio.astype(np.float32))
    recovered, err = ggwave_decode_audio(audio, sr)
    ok = int(recovered == payload)
    goodput = (8 * len(payload.encode("utf-8")) / air) if ok and air > 0 else 0.0
    return TrialResult(
        stack=f"ggwave_ultrasound_p{protocol_id}",
        trial=trial,
        payload=payload,
        success=ok,
        recovered=recovered or "",
        error=err if not ok else "",
        airtime_s=air,
        listen_s=max(listen, elapsed),
        peak=peak,
        payload_goodput_bps=goodput,
        wav=str(wav_rx.relative_to(ROOT)) if wav_rx.is_relative_to(ROOT) else str(wav_rx),
    )


def trial_nearus_fast(
    *,
    trial: int,
    payload: str,
    remote: str,
    rdir: str,
    outdev: int,
    in_dev: int,
    out_dir: Path,
) -> TrialResult:
    from src.modulation import ModulationConfig
    from src.protocol import encode_message, estimate_duration
    from src.receiver import decode_from_samples

    tsym = 0.12
    f0, f1 = 15000.0, 16000.0
    amp = 0.30
    cfg = ModulationConfig(
        sample_rate=48000,
        symbol_duration=tsym,
        frequency_zero=f0,
        frequency_one=f1,
        amplitude=amp,
    )
    air = float(
        estimate_duration(payload, tsym, repeats=1, inter_frame_silence=0.0, fec="none")
    )
    listen = air + 6.0
    sr = 48000
    n = int(listen * sr)
    rec = sd.rec(n, samplerate=sr, channels=1, dtype="float32", device=in_dev)
    time.sleep(1.0)
    remote_cmd = (
        f"cd {shlex.quote(rdir)} && . .venv/bin/activate && "
        f"PYTHONPATH=. python -m src.transmitter --message {shlex.quote(payload)} "
        f"--modulation cpfsk --fec none --symbol-duration {tsym} "
        f"--frequency-zero {f0} --frequency-one {f1} "
        f"--amplitude {amp} --repeats 1 --inter-frame-silence 0.0 "
        f"--output-device {outdev} --near-ultrasonic"
    )
    p = subprocess.Popen(
        ["ssh", remote, remote_cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    sd.wait()
    out, err = p.communicate(timeout=300)
    audio = rec[:, 0].astype(np.float64)
    peak = float(np.max(np.abs(audio)))
    wav_rx = out_dir / f"nearus_fast_rx_t{trial}.wav"
    wavfile.write(str(wav_rx), sr, audio.astype(np.float32))
    bits = encode_message(payload, fec="none")
    stats, _, result = decode_from_samples(
        audio,
        cfg,
        min_energy=1e-6,
        min_ratio=1.08,
        expected_bits=bits,
        fec="none",
        sync_mode="correlation",
        apply_bandpass=False,
        frequency_search_hz=150.0,
        frequency_search_step_hz=25.0,
        symbol_duration_search_percent=3.0,
        symbol_duration_search_steps=5,
        timing_steps=16,
    )
    ok = int(bool(result.success and stats.recovered_message == payload))
    goodput = (8 * len(payload.encode("utf-8")) / air) if ok and air > 0 else 0.0
    err_s = ""
    if p.returncode != 0:
        err_s = f"ssh_rc={p.returncode}"
    elif not ok:
        err_s = result.error or "decode_fail"
    if "Transmission finished" not in (out or "") and p.returncode == 0:
        err_s = (err_s + ";tx_incomplete").strip(";")
    return TrialResult(
        stack="near_us_fast",
        trial=trial,
        payload=payload,
        success=ok,
        recovered=stats.recovered_message or "",
        error=err_s,
        airtime_s=air,
        listen_s=listen,
        peak=peak,
        payload_goodput_bps=goodput,
        wav=str(wav_rx.relative_to(ROOT)) if wav_rx.is_relative_to(ROOT) else str(wav_rx),
    )


def summarize(rows: List[TrialResult]) -> List[dict]:
    stacks = sorted({r.stack for r in rows})
    out = []
    for stack in stacks:
        rs = [r for r in rows if r.stack == stack]
        n = len(rs)
        succ = sum(r.success for r in rs)
        air_ok = sum(r.airtime_s for r in rs if r.success)
        pb = len(rs[0].payload.encode("utf-8"))
        gp = (8 * pb * succ / air_ok) if air_ok > 0 else 0.0
        out.append(
            {
                "stack": stack,
                "n": n,
                "successes": succ,
                "fer": 1.0 - succ / n if n else 1.0,
                "mean_airtime_s_all": float(np.mean([r.airtime_s for r in rs])),
                "mean_airtime_s_success": float(np.mean([r.airtime_s for r in rs if r.success]))
                if succ
                else None,
                "payload_goodput_bps": gp,
                "payload": rs[0].payload,
                "provenance": "PHYSICAL_RX",
            }
        )
    return out


def main() -> int:
    _ensure_ggwave()
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--payload", default="HELLO")
    ap.add_argument(
        "--ggwave-protocols",
        default="3,5",
        help="Comma-separated ggwave ultrasound protocol IDs (3=Normal,4=Fast,5=Fastest)",
    )
    ap.add_argument("--ggwave-volume", type=int, default=50)
    ap.add_argument("--input-device", type=int, default=0)
    ap.add_argument(
        "--stacks",
        default="both",
        choices=["both", "ggwave", "nearus"],
    )
    args = ap.parse_args()

    remote = os.environ.get("ACOUSTIC_REMOTE_TX")
    rdir = os.environ.get("ACOUSTIC_REMOTE_DIR")
    outdev = int(os.environ.get("ACOUSTIC_REMOTE_OUTPUT_DEVICE", "0"))
    if not remote or not rdir:
        raise SystemExit("Set ACOUSTIC_REMOTE_TX and ACOUSTIC_REMOTE_DIR")

    out_dir = ROOT / "output" / "part3" / "ggwave-bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[TrialResult] = []
    gg_protocols = [int(x) for x in args.ggwave_protocols.split(",") if x.strip()]

    print(
        f"A/B PHYSICAL_RX payload={args.payload!r} N={args.trials} "
        f"TX={remote} outdev={outdev} ggwave_protocols={gg_protocols}",
        flush=True,
    )

    if args.stacks in ("both", "ggwave"):
        for protocol_id in gg_protocols:
            for t in range(args.trials):
                print(
                    f"\n=== ggwave ultrasound protocol={protocol_id} trial {t} ===",
                    flush=True,
                )
                r = trial_ggwave(
                    trial=t,
                    payload=args.payload,
                    protocol_id=protocol_id,
                    volume=args.ggwave_volume,
                    remote=remote,
                    rdir=rdir,
                    outdev=outdev,
                    in_dev=args.input_device,
                    out_dir=out_dir,
                )
                print(
                    f"success={r.success} recovered={r.recovered!r} air={r.airtime_s:.2f}s "
                    f"peak={r.peak:.3f} err={r.error}",
                    flush=True,
                )
                rows.append(r)

    if args.stacks in ("both", "nearus"):
        for t in range(args.trials):
            print(f"\n=== near-us-fast trial {t} ===", flush=True)
            r = trial_nearus_fast(
                trial=t,
                payload=args.payload,
                remote=remote,
                rdir=rdir,
                outdev=outdev,
                in_dev=args.input_device,
                out_dir=out_dir,
            )
            print(
                f"success={r.success} recovered={r.recovered!r} air={r.airtime_s:.2f}s "
                f"peak={r.peak:.3f} err={r.error}",
                flush=True,
            )
            rows.append(r)

    if not rows:
        raise SystemExit("No trials executed")

    # write outputs
    trial_path = out_dir / "all_trials.csv"
    with trial_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(asdict(rows[0]).keys()))
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))
    summary = summarize(rows)
    sum_path = out_dir / "summary.csv"
    with sum_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "payload": args.payload,
        "trials": args.trials,
        "ggwave_protocols": gg_protocols,
        "summary": summary,
        "note": "PHYSICAL_RX A/B; WAV paths under output/part3/ggwave-bench/ (may be gitignored)",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("\nSUMMARY", flush=True)
    for s in summary:
        print(s, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
