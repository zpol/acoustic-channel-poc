# Results summary

Exact git commit at last physical campaign: `f73d7cb3d9f0fa69fdd5a2d7bfaf98aebca4db00` (working tree may contain newer uncommitted upgrades).

## Scope

Authorized lab/conference demo. Synthetic payloads only. Metrics use **estimated_detector_snr_db** (not SPL) and labelled provenance.

## Physical hardware (redacted)

- **TX:** remote ThinkPad `t11` (sof-hda-dsp speakers, sounddevice output index 1)
- **RX:** lab capture host, Rear Mic / ALC897 Analog path, device 0
- Room: lab; nominal mic orientation toward remote speakers

## Physical calibration (this lab)

### Audible 2–10 kHz — PHYSICAL_RX

Path: `output/samples/calibration-audible-physical/`

- Latency detected (~1.6 s including remote start delay)
- Peak energy near **3750 Hz**
- Cal recommendation: **2000 / 3750 Hz**
- **Demo-day live pair (proven):** **3500 / 7500 Hz**, Tsym 0.12 s, CPFSK

### Near-ultrasonic 15–21 kHz — PHYSICAL_RX

Path: `output/samples/calibration-near-us-physical/`

- Absolute `estimated_detector_snr_db` mostly **negative**
- Energy-ranked candidates around 15.75/18 kHz still weak
- **Honest result:** near-US live decode not reliable on this TX/RX pair; use for education / spectrograms only

## Physical campaign A — same-host CPFSK audible

Path: `experiments/20260730T184649-local-audible-cpfsk/`  
Provenance: **PHYSICAL_RX**

| Item | Value |
|------|-------|
| Carriers | 3500 / 7500 Hz |
| Symbol duration | 0.12 s |
| Modulation | CPFSK |
| FEC | none |
| Trials | 10 |
| Frame success | **6/10 (60%)** |
| Notes | CRC failures on longer payloads; latency pilot not confidently detected |

## Physical campaign B — remote TX → local RX

Path: `experiments/20260730T190041-remote-t11-tx-local-rx/`  
Provenance: **PHYSICAL_RX**

| Item | Value |
|------|-------|
| Carriers | 3500 / 7500 Hz |
| Symbol duration | 0.12 s |
| Modulation | CPFSK |
| Amplitude | 0.28 |
| Trials | 10 |
| Frame success | **8/10 (80%)** |
| Payloads | HELLO, DEMO-LAB-2027, ACOUSTIC-CHANNEL |

Raw WAVs retained for failed trials (CRC mismatches).

## Physical campaign C — remote TX + Hamming(7,4)

Path: `experiments/20260730T192412-remote-cpfsk-hamming74/`  
Provenance: **PHYSICAL_RX**

| Item | Value |
|------|-------|
| Modulation | CPFSK |
| FEC | hamming74 |
| Payload | HELLO |
| Trials | 4 |
| Frame success | **4/4 (100%)** |

## Simulation

- FEC + CPFSK sim experiment: `experiments/*-sim-cpfsk-hamming74` (3/3 OK)
- Matrix: `output/benchmark/` (SIMULATED_RX) — see `report.md`

## Modulation comparison (GENERATED_TX)

Path: `output/modulation-comparison/`

CPFSK did **not** show lower audible-band leakage than legacy BFSK in the 18.5/19.5 kHz generated comparison (`cpfsk_lower_audible_leakage: false`). Do not claim CPFSK is quieter without measurement.

## Limitations

- Live success is condition-dependent (room, distance, audio processing)
- Latency estimation may fail; do not fabricate alignment
- Near-ultrasonic not mandatory; requires measured usable response
- README historical “100%” claims must be read as specific profile/session results, not universal

## Reproducibility

```bash
source .venv/bin/activate
pytest -q
python scripts/run_experiment_matrix.py
python -m src.experiment --non-interactive --remote-tx nkn@192.168.68.109 \
  --remote-output-device 1 --trials 10 --modulation cpfsk
```

## Figures

| Figure | Provenance |
|--------|------------|
| `output/calibration/response.png` | SIMULATED_RX when `--dry-run` |
| `output/modulation-comparison/*.png` | GENERATED_TX |
| `output/benchmark/*.png` | SIMULATED_RX |
| `experiments/*/trial-*/rx.wav` | PHYSICAL_RX |
