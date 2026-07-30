# Curated demo samples

Payloads are synthetic (`DEMO-LAB-2027`, `HELLO`, …). Nothing contains `POL`.

## Provenance

| Path | Provenance |
| --- | --- |
| `fast_*`, `reliable_*`, `turbo_*`, `demo_*`, `near_us_*` | GENERATED_TX / SIMULATED_RX |
| `calibration-audible-physical/` | **PHYSICAL_RX** (2–10 kHz sweep) |
| `calibration-near-us-physical/` | **PHYSICAL_RX** (15–21 kHz sweep) |
| `replay/` | **PHYSICAL_RX** (remote TX → local mic, HELLO, CRC valid) |
| `experiment-summaries/` | Summaries of PHYSICAL_RX / SIMULATED campaigns |

`*_rx_sim.wav` files are **simulated** microphone captures, not live room recordings.

## Demo-day

See `docs/demo-day-configs.md`. Primary live path: audible **3500/7500 Hz**, CPFSK, 0.12 s.
Near-US is educational on this hardware (weak measured detector SNR).
