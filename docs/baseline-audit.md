# Baseline audit

**Date:** 2026-07-30  
**Git commit:** `f73d7cb3d9f0fa69fdd5a2d7bfaf98aebca4db00`  
**Python:** 3.12.3  

## Tests executed

| Suite | Result |
| --- | --- |
| `pytest -q` | **45 passed** in ~3.7 s |
| `python -m src.benchmark --simulate` (HELLO, DEMO-LAB-2027, ACOUSTIC-CHANNEL) | **3/3 (100%)**, mean BER 0.0 |

## Current architecture

```text
CLI (transmitter / receiver / calibration / benchmark / audio_devices)
        │
        ├── protocol.py     PREAMBLE|SYNC|VER|LEN|PAYLOAD|CRC16
        ├── modulation.py   BFSK only, Goertzel, bandpass, timing search
        ├── visualizer.py   PNG plots
        └── audio_devices.py PortAudio listing
```

### Modulation (as of baseline)

* **BFSK only** — phase is carried across symbols (`generate_tone` → `next_phase`), but each symbol still has a **per-symbol amplitude fade** (5%). This is **not** continuous-phase FSK (CPFSK).
* Defaults (`fast` profile): 120 ms, 3500/7500 Hz, amplitude 0.20.
* Demodulation: Goertzel at f0/f1, soft/hard decisions, optional band-pass (±800 Hz).

### Synchronization (as of baseline)

* Exact hard-bit preamble+sync match after optional timing-offset search (`find_best_timing_offset`).
* Soft-bit repair and majority vote across repeated frames.
* No soft preamble correlation score used for acceptance beyond timing search.
* No frequency-offset neighbourhood search.
* No measured duplex latency compensation.

### Filtering

* 4th-order Butterworth band-pass around the BFSK pair (default on).

### Calibration / benchmark

* Calibration supports dry-run (synthetic) and live play+record, but **does not** measure duplex latency or save a full physical experiment package.
* Benchmark supports `--simulate` and live duplex; `scripts/live_benchmark.py` uses two processes.

## Existing commands

```bash
python -m src.audio_devices
python -m src.transmitter --message DEMO-LAB-2027 [--dry-run] [--profile fast|reliable|turbo]
python -m src.receiver --simulate|--input-device N
python -m src.calibration [--dry-run] [--near-ultrasonic]
python -m src.benchmark --simulate|live
PYTHONPATH=. python scripts/live_benchmark.py
```

## Artefact provenance (baseline)

| Location | Provenance |
| --- | --- |
| `output/samples/*_tx.*` | **GENERATED_TX** |
| `output/samples/*_rx_sim.*` | **SIMULATED_RX** |
| `output/screenshots/*` | Generated/simulated copies for docs |
| Root `output/hw_*.wav`, `tp_*.wav`, `spd_*`, `bench_*` | **PHYSICAL_RX** (ad-hoc, gitignored, unlabeled) |

## README claims requiring physical evidence

1. “100% frame success at 120 ms + 3.5/7.5 kHz” on this lab PC — **reconcile with ~67% run** recorded in earlier live_benchmark notes.
2. Near-ultrasonic viability — screenshots are TX dry-runs; physical success not proven in-repo.
3. Default amplitude documented as 0.15 in ethics bullet but code default is 0.20 — inconsistency.

## Limitations to address in this upgrade

* No CPFSK / continuous-phase implementation.
* No FEC (CRC detect-only).
* No hardware profile / latency pilot.
* No physical experiment directory format with provenance.
* No stage demo / replay UI.
* No audible-leakage metrics.
* Sync is brittle under frequency offset and residual timing drift.
* Simulated vs physical artefacts not labeled in plots/JSON.

## Regressions to avoid

* Keep existing CLI modules and flags working.
* Keep deterministic unit tests hardware-free.
* Do not delete curated `output/samples` or `output/screenshots`.
* Do not present simulated results as physical.
* Do not force 18.5/19.5 kHz if calibration shows roll-off.

## Upgrade plan (this work)

Phases B→G: CPFSK + leakage analysis → hardware profile + latency + physical calibration → correlation sync + timing/freq recovery → Hamming(7,4) → physical experiments → stage demo + docs.
