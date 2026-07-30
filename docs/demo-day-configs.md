# Demo-day configurations

Provenance for live audio: **PHYSICAL_RX**. Generated visuals: **GENERATED_TX**.

## AUDIBLE (primary live path)

Proven live on remote TX `t11` → local mic:

| Param | Value |
|-------|-------|
| f0 / f1 | **3500 / 7500 Hz** |
| Symbol duration | **0.12 s** |
| Modulation | **cpfsk** |
| FEC | `none` or `hamming74` |
| Amplitude | 0.25–0.28 |
| Repeats | 2 |

Physical cal sweep (`output/calibration-audible-physical`, PHYSICAL_RX) peaked near **3750 Hz** and recommends **2000/3750** as MOST_RELIABLE under that sweep. Prefer the **proven live** 3500/7500 pair for stage reliability.

### Fast audible (speed demo)

Measured on the same remote-TX → local-mic path with payload `DEMO_DEMO_334` (PHYSICAL_RX):

| Tsym | Carriers | Repeats | TX ≈ | Live trials |
|------|----------|---------|------|-------------|
| **0.07 s** | 3000 / 8000 Hz | 1 | ~11.8 s | **3/3 CRC VALID** ← recommended fast |
| 0.08 s | 3000 / 8000 Hz | 1 | ~13.4 s | 2/2 (+ earlier single OK) |
| 0.04 s | 3000 / 8000 Hz | 1 | ~6.7 s | 2/3 (aggressive / flaky) |
| 0.05–0.06 s | 3000 / 8000 Hz | 1 | — | CRC failures in first sweep |

```bash
# Fast path (~12 s airtime for DEMO_DEMO_334)
python -m src.live_monitor --remote-tx nkn@192.168.68.109 \
  --remote-output-device 1 --message DEMO_DEMO_334 --modulation cpfsk \
  --symbol-duration 0.07 --frequency-zero 3000 --frequency-one 8000 \
  --repeats 1 --amplitude 0.30

# Aggressive (~7 s) — expect occasional CRC fail
python -m src.live_monitor --remote-tx nkn@192.168.68.109 \
  --remote-output-device 1 --message DEMO_DEMO_334 --modulation cpfsk \
  --symbol-duration 0.04 --frequency-zero 3000 --frequency-one 8000 \
  --repeats 1 --amplitude 0.30
```

### Commands (reliable default)

```bash
# Live monitor — UI live; CRC decode after capture (~47s for DEMO-LAB-2027 ×2 @ 0.12s)
python -m src.live_monitor --remote-tx nkn@192.168.68.109 \
  --remote-output-device 1 --message DEMO-LAB-2027 --modulation cpfsk

# Or stage wizard
python -m src.stage_demo --wizard

# Replay fallback
python -m src.stage_demo --replay output/samples/replay/rx.wav --message HELLO
```

## NEAR-ULTRASONIC (experimental / educational)

Physical cal `output/calibration-near-us-physical` (PHYSICAL_RX) shows **low / negative estimated_detector_snr_db** across 15–21 kHz on this TX/RX pair. Do **not** promise a live near-US decode on stage.

Use near-US for:

1. Spectrogram / leakage comparison (`python -m src.signal_analysis compare-modulations`)
2. Audible frequency-shifted preview of the same bits
3. Honest slide: “hardware roll-off, not Nyquist”

Optional experimental try (expect failure unless re-calibrated on site):

```bash
python -m src.live_monitor --near-ultrasonic \
  --frequency-zero 15750 --frequency-one 18000 \
  --symbol-duration 0.20 --amplitude 0.10 \
  --remote-tx nkn@192.168.68.109 --remote-output-device 1 \
  --message HELLO
```

## Calibration artefacts

| Path | Band | Provenance |
|------|------|------------|
| `output/samples/calibration-audible-physical/` | 2–10 kHz | PHYSICAL_RX |
| `output/samples/calibration-near-us-physical/` | 15–21 kHz | PHYSICAL_RX |

## Evidence campaigns

- Remote audible CPFSK: `experiments/20260730T190041-remote-t11-tx-local-rx/` → **8/10**
- Remote + Hamming: `experiments/20260730T192412-remote-cpfsk-hamming74/` → **4/4**
- Fast `DEMO_DEMO_334` @ 0.07 s / 3–8 kHz → **3/3** (see table above)
