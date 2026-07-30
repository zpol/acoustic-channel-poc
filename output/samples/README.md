# Curated demo samples (no live captures)

All payloads use synthetic messages such as `DEMO-LAB-2027` or `HELLO`.
Nothing in this folder contains the substring `POL`.

| File prefix | Meaning |
| --- | --- |
| `fast_120ms_*` | Default/fast profile (3.5/7.5 kHz, 120 ms) |
| `reliable_200ms_*` | High-reliability profile (4/6 kHz, 200 ms) |
| `turbo_80ms_*` | Experimental faster profile (3/8 kHz, 80 ms) |
| `near_us_HELLO_*` | Near-ultrasonic dry-run (18.5/19.5 kHz) |
| `calibration_*.png` | Frequency-response calibration plots |
| `demo_*` | Canonical demo TX artefacts |

`*_rx_sim.wav` files are **simulated** microphone captures (noise + timing offset), not live room recordings.
