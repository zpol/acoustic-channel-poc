"""Spectrum metrics, modulation comparison, and defensive heuristics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, filtfilt, welch

from src.modulation import (
    DEFAULT_SAMPLE_RATE,
    ModulationConfig,
    modulate,
)
from src.protocol import encode_message, validate_payload
from src.provenance import Provenance

console_err = sys.stderr


def band_energy(
    samples: np.ndarray,
    sample_rate: int,
    f_lo: float,
    f_hi: float,
) -> float:
    """Estimate energy in [f_lo, f_hi] via Welch PSD."""
    if len(samples) < 64:
        return 0.0
    freqs, psd = welch(samples, fs=sample_rate, nperseg=min(4096, len(samples)))
    mask = (freqs >= f_lo) & (freqs <= f_hi)
    if not np.any(mask):
        return 0.0
    trapz = getattr(np, "trapezoid", None) or np.trapz
    return float(trapz(psd[mask], freqs[mask]))


def audible_leakage_metrics(
    samples: np.ndarray,
    sample_rate: int,
    carrier_zero: float,
    carrier_one: float,
    audible_ceiling_hz: float = 17_000.0,
    carrier_bw_hz: float = 500.0,
) -> Dict[str, float]:
    """Estimate in-band vs below-ceiling energy (not a hearing test)."""
    total = band_energy(samples, sample_rate, 20.0, sample_rate / 2 - 1)
    audible = band_energy(samples, sample_rate, 20.0, audible_ceiling_hz)
    c0 = band_energy(
        samples,
        sample_rate,
        max(20.0, carrier_zero - carrier_bw_hz),
        carrier_zero + carrier_bw_hz,
    )
    c1 = band_energy(
        samples,
        sample_rate,
        max(20.0, carrier_one - carrier_bw_hz),
        carrier_one + carrier_bw_hz,
    )
    carrier = c0 + c1
    # Leakage: energy below ceiling relative to carrier band
    ratio_db = 10.0 * np.log10((audible + 1e-20) / (carrier + 1e-20))
    splatter_db = 10.0 * np.log10((total - carrier + 1e-20) / (carrier + 1e-20))
    return {
        "audible_band_energy": audible,
        "carrier_band_energy": carrier,
        "total_energy": total,
        "audible_leakage_ratio_db": float(ratio_db),
        "spectral_splatter_ratio_db": float(splatter_db),
        "audible_ceiling_hz": audible_ceiling_hz,
    }


def save_spectrum_png(
    samples: np.ndarray,
    sample_rate: int,
    path: Path,
    title: str,
) -> None:
    freqs, psd = welch(samples, fs=sample_rate, nperseg=min(4096, len(samples)))
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.semilogy(freqs, psd + 1e-20)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSD")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def compare_modulations(
    message: str,
    frequency_zero: float,
    frequency_one: float,
    symbol_duration: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    amplitude: float = 0.15,
    out_dir: Path = Path("output/modulation-comparison"),
) -> Dict[str, object]:
    """Generate BFSK vs CPFSK artefacts and leakage metrics."""
    validate_payload(message)
    cfg = ModulationConfig(
        sample_rate=sample_rate,
        symbol_duration=symbol_duration,
        frequency_zero=frequency_zero,
        frequency_one=frequency_one,
        amplitude=amplitude,
        near_ultrasonic=max(frequency_zero, frequency_one) > 17000,
    )
    bits = encode_message(message)
    bfsk = modulate(bits, cfg, modulation="bfsk")
    cpfsk = modulate(bits, cfg, modulation="cpfsk")
    out_dir.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(out_dir / "bfsk.wav"), sample_rate, bfsk.astype(np.float32))
    wavfile.write(str(out_dir / "cpfsk.wav"), sample_rate, cpfsk.astype(np.float32))
    m_bfsk = audible_leakage_metrics(bfsk, sample_rate, frequency_zero, frequency_one)
    m_cpfsk = audible_leakage_metrics(cpfsk, sample_rate, frequency_zero, frequency_one)
    save_spectrum_png(
        bfsk,
        sample_rate,
        out_dir / "bfsk_spectrum.png",
        Provenance.GENERATED_TX.plot_title("BFSK spectrum"),
    )
    save_spectrum_png(
        cpfsk,
        sample_rate,
        out_dir / "cpfsk_spectrum.png",
        Provenance.GENERATED_TX.plot_title("CPFSK spectrum"),
    )
    # Comparison bar chart
    fig, ax = plt.subplots(figsize=(8, 4))
    labels = ["audible_leakage_ratio_db", "spectral_splatter_ratio_db"]
    x = np.arange(len(labels))
    ax.bar(x - 0.15, [m_bfsk[k] for k in labels], width=0.3, label="BFSK")
    ax.bar(x + 0.15, [m_cpfsk[k] for k in labels], width=0.3, label="CPFSK")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15)
    ax.set_ylabel("dB")
    ax.set_title(
        Provenance.GENERATED_TX.plot_title("BFSK vs CPFSK leakage metrics")
    )
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "comparison.png", dpi=120)
    plt.close(fig)
    metrics = {
        "provenance": Provenance.GENERATED_TX.value,
        "message": message,
        "frequency_zero": frequency_zero,
        "frequency_one": frequency_one,
        "symbol_duration": symbol_duration,
        "bfsk": m_bfsk,
        "cpfsk": m_cpfsk,
        "cpfsk_lower_audible_leakage": bool(
            m_cpfsk["audible_leakage_ratio_db"] < m_bfsk["audible_leakage_ratio_db"]
        ),
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def apply_lowpass(
    samples: np.ndarray,
    sample_rate: int,
    cutoff_hz: float,
) -> np.ndarray:
    nyq = sample_rate / 2.0
    wn = min(cutoff_hz / nyq, 0.99)
    b, a = butter(6, wn, btype="low")
    return filtfilt(b, a, samples).astype(np.float64)


def detect_channel_heuristic(
    samples: np.ndarray,
    sample_rate: int,
) -> Dict[str, object]:
    """Heuristic dual-tone / symbol-periodicity detector (not malware detection)."""
    freqs, psd = welch(samples, fs=sample_rate, nperseg=min(8192, len(samples)))
    # Find two strongest peaks above 1 kHz
    mask = freqs > 1000
    f = freqs[mask]
    p = psd[mask]
    if len(p) < 10:
        return {"confidence": 0.0, "note": "too short"}
    idx = np.argsort(p)[-8:]
    peaks = sorted({round(float(f[i]) / 50) * 50 for i in idx}, reverse=True)
    candidates = peaks[:2]
    confidence = 0.0
    if len(candidates) >= 2:
        sep = abs(candidates[0] - candidates[1])
        if 200 <= sep <= 8000:
            confidence = 0.45
        if sep >= 500:
            confidence += 0.15
    return {
        "candidate_carriers_hz": candidates,
        "confidence": confidence,
        "description": (
            "Heuristic resemblance to a dual-tone structured channel. "
            "Not a malware detector."
        ),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.signal_analysis")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cmp = sub.add_parser("compare-modulations")
    p_cmp.add_argument("--message", default="DEMO-LAB-2027")
    p_cmp.add_argument("--frequency-zero", type=float, default=18500.0)
    p_cmp.add_argument("--frequency-one", type=float, default=19500.0)
    p_cmp.add_argument("--symbol-duration", type=float, default=0.20)
    p_cmp.add_argument(
        "--out-dir", type=Path, default=Path("output/modulation-comparison")
    )

    p_lp = sub.add_parser("apply-lowpass")
    p_lp.add_argument("--input-wav", type=Path, required=True)
    p_lp.add_argument("--cutoff", type=float, default=17000.0)
    p_lp.add_argument("--output-wav", type=Path, required=True)

    p_det = sub.add_parser("detect-channel")
    p_det.add_argument("--input-wav", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.cmd == "compare-modulations":
        # Near-US comparison requires explicit awareness — warn only
        if max(args.frequency_zero, args.frequency_one) > 17000:
            print(
                "NOTE: generating GENERATED_TX comparison above 17 kHz "
                "(not a physical capture).",
                file=console_err,
            )
        metrics = compare_modulations(
            args.message,
            args.frequency_zero,
            args.frequency_one,
            args.symbol_duration,
            out_dir=args.out_dir,
        )
        print(json.dumps(metrics, indent=2))
        return 0
    if args.cmd == "apply-lowpass":
        sr, data = wavfile.read(str(args.input_wav))
        x = np.asarray(data, dtype=np.float64)
        if x.ndim > 1:
            x = x.mean(axis=1)
        y = apply_lowpass(x, sr, args.cutoff)
        args.output_wav.parent.mkdir(parents=True, exist_ok=True)
        wavfile.write(str(args.output_wav), sr, y.astype(np.float32))
        print(f"Wrote {args.output_wav}")
        return 0
    if args.cmd == "detect-channel":
        sr, data = wavfile.read(str(args.input_wav))
        x = np.asarray(data, dtype=np.float64)
        if x.ndim > 1:
            x = x.mean(axis=1)
        print(json.dumps(detect_channel_heuristic(x, sr), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
