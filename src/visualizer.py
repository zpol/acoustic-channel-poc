"""Visualization helpers for waveforms, spectrograms, and bit timelines."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.modulation import ModulationConfig, SymbolDecision, goertzel


def save_waveform_plot(
    samples: np.ndarray,
    sample_rate: int,
    path: Path | str,
    title: str = "Waveform",
) -> Path:
    """Save a time-domain waveform plot as PNG."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(len(samples)) / sample_rate
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.plot(t, samples, linewidth=0.5, color="#1a5f7a")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.set_title(title)
    ax.set_ylim(-1.05, 1.05)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def save_spectrogram(
    samples: np.ndarray,
    sample_rate: int,
    path: Path | str,
    title: str = "Spectrogram",
    fmin: Optional[float] = None,
    fmax: Optional[float] = None,
) -> Path:
    """Save a spectrogram PNG of *samples*."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    nfft = 2048
    noverlap = nfft // 2
    spec, freqs, times, im = ax.specgram(
        samples,
        NFFT=nfft,
        Fs=sample_rate,
        noverlap=noverlap,
        cmap="magma",
        scale="dB",
    )
    del spec  # unused; im is the image artist
    if fmin is not None or fmax is not None:
        ax.set_ylim(fmin or 0, fmax or sample_rate / 2)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (Hz)")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, label="dB")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def save_energy_over_time(
    samples: np.ndarray,
    config: ModulationConfig,
    path: Path | str,
    title: str = "BFSK energy over time",
) -> Path:
    """Plot Goertzel energy at both BFSK frequencies across symbol windows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sps = config.samples_per_symbol
    n_symbols = len(samples) // sps
    e0_list = []
    e1_list = []
    for i in range(n_symbols):
        window = samples[i * sps : (i + 1) * sps]
        e0_list.append(goertzel(window, config.frequency_zero, config.sample_rate))
        e1_list.append(goertzel(window, config.frequency_one, config.sample_rate))
    t = np.arange(n_symbols) * config.symbol_duration
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(t, e0_list, label=f"f0={config.frequency_zero:.0f} Hz", color="#1a5f7a")
    ax.plot(t, e1_list, label=f"f1={config.frequency_one:.0f} Hz", color="#c45c26")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Goertzel energy")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def save_bit_timeline(
    decisions: Sequence[SymbolDecision],
    symbol_duration: float,
    path: Path | str,
    title: str = "Decoded bit timeline",
) -> Path:
    """Plot decoded bits and confidence over time."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(len(decisions)) * symbol_duration
    bits = [d.bit if d.bit is not None else np.nan for d in decisions]
    conf = [d.confidence for d in decisions]
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(10, 5), sharex=True)
    ax0.step(t, bits, where="post", color="#1a5f7a")
    ax0.set_ylabel("Bit")
    ax0.set_yticks([0, 1])
    ax0.set_ylim(-0.2, 1.2)
    ax0.set_title(title)
    ax0.grid(True, alpha=0.3)
    ax1.plot(t, conf, color="#c45c26")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Confidence")
    ax1.set_ylim(0, 1.05)
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def save_frequency_response(
    frequencies: Sequence[float],
    energies: Sequence[float],
    noise_floor: float,
    path: Path | str,
    recommended: Optional[Tuple[float, float]] = None,
    title: str = "Calibration frequency response",
) -> Path:
    """Save a calibration frequency-response plot."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    freqs = np.asarray(frequencies, dtype=np.float64)
    en = np.asarray(energies, dtype=np.float64)
    snr = 10.0 * np.log10((en + 1e-20) / (noise_floor + 1e-20))
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    ax0.semilogy(freqs, en + 1e-20, color="#1a5f7a", marker="o", markersize=3)
    ax0.axhline(noise_floor, color="#888", linestyle="--", label="Noise floor")
    ax0.set_ylabel("Energy")
    ax0.set_title(title)
    ax0.legend()
    ax0.grid(True, alpha=0.3)
    ax1.plot(freqs, snr, color="#c45c26", marker="o", markersize=3)
    ax1.set_xlabel("Frequency (Hz)")
    ax1.set_ylabel("Estimated SNR (dB)")
    ax1.grid(True, alpha=0.3)
    if recommended is not None:
        for f in recommended:
            ax0.axvline(f, color="#2d6a4f", linestyle=":", alpha=0.8)
            ax1.axvline(f, color="#2d6a4f", linestyle=":", alpha=0.8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
