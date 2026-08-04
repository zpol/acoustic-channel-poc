# Curated demo samples — provenance catalogue

Payloads are synthetic (`DEMO-LAB-2027`, `HELLO`, `DEMO_DEMO_334`, …).
Nothing contains real credentials or private user data.

## Provenance categories

| Label | Meaning |
| --- | --- |
| `GENERATED_TX` | Digitally synthesized transmitter waveform (never a physical capture) |
| `SIMULATED_RX` | Digitally impaired RX (noise/attenuation); not a room recording |
| `PHYSICAL_RX` | Microphone capture of a real acoustic transmission |
| `PHYSICAL_REPLAY` | Verified replay of a `PHYSICAL_RX` WAV through the decoder |

Never treat a generated spectrogram as evidence of successful physical transmission.

## Evidence table

| Artefact | Provenance | Modulation | Result | Suitable for article |
| --- | --- | --- | --- | --- |
| `demo_tx.wav` / `demo_spectrogram.png` | GENERATED_TX | BFSK/CPFSK (demo) | N/A (TX only) | Yes — architecture / TX spectrum |
| `reliable_200ms_*` | GENERATED_TX / SIMULATED_RX | BFSK profile | Simulated CRC path | Yes — label as simulated |
| `fast_120ms_*` | GENERATED_TX / SIMULATED_RX | BFSK fast | Simulated | Yes — label as simulated |
| `turbo_80ms_*` | GENERATED_TX / SIMULATED_RX | BFSK turbo | Simulated | Yes — label as simulated |
| `near_us_HELLO_*` | GENERATED_TX | near-US carriers | Digital TX only | Yes — generation works digitally |
| `calibration-audible-physical/` | PHYSICAL_RX | sweep 2–10 kHz | Response measured | Yes — audible hardware response |
| `calibration-near-us-physical/` | PHYSICAL_RX | sweep 15–21 kHz | Weak / negative detector SNR | Yes — near-US **calib** weakness (not the full recovery story) |
| `experiment-summaries/20260804-nearus-payloads/` | PHYSICAL_RX | CPFSK 15/16 kHz recovery | CRC VALID documented payloads | Yes — cite M/N from summary |
| `replay/rx.wav` (+ `rx.wav.meta.json`) | PHYSICAL_RX | CPFSK 3500/7500, 0.12 s, FEC none | CRC VALID (`HELLO`) | Yes — verified physical capture |
| `replay/tx.wav` | GENERATED_TX | matching TX | N/A | Yes — pair with RX, do not call physical |
| `experiment-summaries/` | PHYSICAL_RX / SIMULATED summaries | various | campaign-dependent | Yes — cite trial counts |

## Per-directory notes

### Root generated / simulated pairs (`*_tx.wav`, `*_rx_sim.wav`)

* Produced by earlier dry-run / `--simulate` tooling.
* Symbol durations: 200 ms (reliable), 120 ms (fast), 80 ms (turbo).
* FEC: none in these curated pairs unless noted in filenames.
* Suitable for illustrating DSP; **not** physical success.

### `calibration-audible-physical/`

* PHYSICAL_RX frequency sweep (~2–10 kHz).
* Command family: `scripts/physical_calibration_remote.py --band audible` (SSH playback coordination optional).
* Shows usable audible-band energy on the tested hardware.

### `calibration-near-us-physical/`

* PHYSICAL_RX near-ultrasonic sweep (~15–21 kHz).
* Demonstrates **weak detector response** on the tested speaker–microphone chain.
* Do **not** claim that this sweep alone proves live decode is impossible; recovery used a separate slow profile (see `docs/near-us-recovery-campaign.md` and `experiment-summaries/20260804-nearus-payloads/`).
* Do **not** treat GENERATED_TX near-US spectrograms as physical success.
### `replay/`

* Verified PHYSICAL_RX capture (`HELLO`, CPFSK, 3500/7500 Hz, 0.12 s, FEC none).
* Replay requires `rx.wav.meta.json` (schema + SHA-256). Fail-closed if missing/mismatched.
* Decode: `python -m src.replay --input-wav output/samples/replay/rx.wav`

### `experiment-summaries/`

* Redacted publishable summaries of campaigns (hostnames/IPs replaced with documentation placeholders).
* Full WAV dumps may exist under local `experiments/` and are not required for the article.

## Demo-day pointers

See `docs/demo-day-configs.md` and `configs/conference-audible-demo.yaml`.
Primary live path: audible CPFSK; prefer stating trial counts (e.g. 3/3 at 70 ms).
Near-US remains educational on this hardware.
