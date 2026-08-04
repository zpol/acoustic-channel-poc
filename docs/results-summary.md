# Results summary

Docs and code for the conference upgrade live on `main` (see `git log -5 --oneline`).
Physical speed notes below refer to remote TX `remote-lab-tx` → local mic captures labelled **PHYSICAL_RX**.

## Campaign register (one row per session)

Non-monotonic results may reflect synchronization, reflections, device latency,
frequency response and **small sample sizes** — do not merge into one success rate.

| Campaign ID | Date | Git commit (approx) | Hardware | TX | RX | Payload | Distance / orientation | Room | Trials | CRC-valid | CRC fail | Sync fail | Duration | Provenance |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| local-audible-cpfsk-120 | 2026-07-30 | 478b17a… | same-host speakers→mic | CPFSK 3500/7500, 0.12 s, amp~0.25 | local mic | mixed HELLO / DEMO… | ~30–50 cm | lab | 10 | 6 | 4 | 0 noted | ~session | PHYSICAL_RX |
| remote-tx-local-rx-120 | 2026-07-30 | 478b17a… | remote speakers → local mic | CPFSK 3500/7500, 0.12 s, amp 0.28 | local mic | HELLO / DEMO-LAB-2027 / ACOUSTIC-CHANNEL | desk spacing | lab | 10 | 8 | 2 | earlier session had sync fails | ~session | PHYSICAL_RX |
| remote-hamming74-HELLO | 2026-07-30 | 478b17a… | remote → local | CPFSK + hamming74 | local mic | HELLO | desk | lab | 4 | 4 | 0 | 0 | short | PHYSICAL_RX |
| remote-fast-70ms | 2026-07-30 | 478b17a… | remote → local | CPFSK 3000/8000, 0.07 s, repeats=1 | local mic | DEMO_DEMO_334 | desk | lab | 3 | 3 | 0 | 0 | ~12 s TX | PHYSICAL_RX |
| remote-fast-40ms | 2026-07-30 | 478b17a… | remote → local | CPFSK 3000/8000, 0.04 s | local mic | DEMO_DEMO_334 | desk | lab | 3 | 2 | 1 | 0 | ~7 s TX | PHYSICAL_RX |
| remote-fast-50-60ms-fail | 2026-07-30 | 478b17a… | remote → local | CPFSK 3000/8000, 0.05–0.06 s | local mic | DEMO_DEMO_334 | desk | lab | sweep | 0 in initial sweep | yes | possible | short | PHYSICAL_RX |
| cal-audible-physical | 2026-07-30 | 478b17a… | remote sweep TX | tones 2–10 kHz | local mic | N/A (sweep) | desk | lab | sweep | N/A | N/A | N/A | minutes | PHYSICAL_RX |
| cal-near-us-physical | 2026-07-30 | 478b17a… | remote sweep TX | tones 15–21 kHz | local mic | N/A | desk | lab | sweep | weak/neg. detector SNR (calib) | — | — | minutes | PHYSICAL_RX |
| nearus-recovery-HELLO | 2026-08-04 | 8bdc9be… | remote TX → local mic | CPFSK 15/16 kHz, 0.25 s, hamming74×2 | local mic | HELLO | desk | lab | 1 | 1 | 0 | 0 | ~session | PHYSICAL_RX |
| nearus-payloads-20260804 | 2026-08-04 | 8bdc9be… | remote TX → local mic | same recovery profile | local mic | see summary | desk | lab | 5 | 5 CRC VALID; 4/4 exact after quote fix | 0 CRC fail | 0 | ~session | PHYSICAL_RX |
| sim-cpfsk-hamming74 | 2026-07-30 | 478b17a… | none | CPFSK + FEC | simulated | HELLO | N/A | N/A | 3 | 3 | 0 | 0 | short | SIMULATED_RX |

Earlier historical note: **120 ms** was a strong operating point for the remote audible setup before faster 70 ms trials were identified.

## Physical hardware (redacted)

- **TX:** remote ThinkPad `remote-lab-tx` (sof-hda-dsp speakers, sounddevice output index 1)
- **RX:** lab capture host, Rear Mic / ALC897 Analog path, device 0
- Room: lab; nominal mic orientation toward remote speakers

## Physical calibration (this lab)

### Audible 2–10 kHz — PHYSICAL_RX

Path: `output/samples/calibration-audible-physical/`

- Latency detected (~1.6 s including remote start delay)
- Peak energy near **3750 Hz**
- Cal recommendation: **2000 / 3750 Hz**
- **Demo-day live pair (proven):** **3500 / 7500 Hz**, Tsym 0.12 s, CPFSK

### Near-ultrasonic 15–21 kHz — PHYSICAL_RX (calibration)

Path: `output/samples/calibration-near-us-physical/`

- Absolute `estimated_detector_snr_db` mostly **negative**
- Energy-ranked candidates around 15.75/18 kHz still weak
- **Calib honest result:** the sweep alone does **not** look like a robust modem band; theory-driven 18.5/19.5 kHz pairs remain poor on this curve

### Near-US recovery campaign — PHYSICAL_RX (2026-08-04)

Config: CPFSK **15000/16000 Hz**, Tsym **0.25 s**, FEC **hamming74**, repeats **2**, amp **0.30**, freq search ±150 Hz, bandpass off.  
Docs: [`near-us-recovery-campaign.md`](near-us-recovery-campaign.md) · summary: `output/samples/experiment-summaries/20260804-nearus-payloads/summary.md` · figures: `output/article-part2/`

| Item | Result |
| --- | --- |
| HELLO | **1/1** CRC VALID (exact) |
| Payload campaign | **5/5** CRC VALID; **4/4** exact intended strings after `shlex.quote` fix (one pre-fix trial CRC-validated a shell-expanded TX string) |

Small documented N — do **not** publish as “100% reliable” or as proof that default near-US settings work.

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

Path: local dump `experiments/20260730T190041-remote-*-tx-local-rx/` (hostname redacted in publishable copies under `output/samples/experiment-summaries/`)  
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

## Physical campaign D — fast audible `DEMO_DEMO_334`

Provenance: **PHYSICAL_RX** (remote `remote-lab-tx` TX → local mic). Modulation CPFSK, carriers 3000/8000 Hz, repeats=1.

| Tsym | Approx TX | Result |
|------|-----------|--------|
| 0.07 s | ~11.8 s | **3/3 CRC VALID** (recommended fast demo) |
| 0.08 s | ~13.4 s | 2/2 CRC VALID |
| 0.04 s | ~6.7 s | 2/3 CRC VALID (aggressive) |
| 0.05–0.06 s | — | CRC failures in initial sweep |

See `docs/demo-day-configs.md` for exact commands.

## Simulation

- FEC + CPFSK sim experiment: `experiments/*-sim-cpfsk-hamming74` (3/3 OK)
- Matrix: `output/benchmark/` (SIMULATED_RX) — see `report.md`

## Modulation comparison (GENERATED_TX)

Path: `output/modulation-comparison/`

CPFSK did **not** show lower audible-band leakage than legacy BFSK in the 18.5/19.5 kHz generated comparison (`cpfsk_lower_audible_leakage: false`). Do not claim CPFSK is quieter without measurement.

## Limitations

- Live success is condition-dependent (room, distance, audio processing)
- Latency estimation may fail; do not fabricate alignment
- Near-ultrasonic not mandatory; calib SNR can be negative even when a slow recovery profile later succeeds
- README historical “100%” claims must be read as specific profile/session results, not universal
- Distinguishing **calibration failure** from **recovery-profile success** is required in public wording

## Reproducibility

```bash
source .venv/bin/activate
pytest -q
python scripts/run_experiment_matrix.py
python -m src.experiment --non-interactive --remote-tx demo-user@tx-host \
  --remote-output-device 1 --trials 10 --modulation cpfsk
```

## Figures

| Figure | Provenance |
|--------|------------|
| `output/calibration/response.png` | SIMULATED_RX when `--dry-run` |
| `output/modulation-comparison/*.png` | GENERATED_TX |
| `output/benchmark/*.png` | SIMULATED_RX |
| `experiments/*/trial-*/rx.wav` | PHYSICAL_RX |
| `output/article/14-audible-vs-near-us-calibration.png` | PHYSICAL_RX |

## Blog

- Part 2 draft: [`docs/blog-part2-nyquist-meets-hardware.md`](blog-part2-nyquist-meets-hardware.md)
- Near-US recovery: [`docs/near-us-recovery-campaign.md`](near-us-recovery-campaign.md)
- Alternative channels (beeper / piezo / infrasound notes): [`docs/alternative-physical-channels.md`](alternative-physical-channels.md)
