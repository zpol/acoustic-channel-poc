# Demo-day configurations

Authorized lab / conference use only. Synthetic payloads only.

SSH may optionally coordinate **playback** on a separate transmitter
(`demo-user@tx-host`). The payload travels through the **acoustic** channel.

## Canonical conference config

File: `configs/conference-audible-demo.yaml`

| Field | Value |
| --- | --- |
| Modulation | CPFSK |
| f0 / f1 | 3000 / 8000 Hz |
| Symbol duration | 70 ms |
| FEC | none (optional `hamming74`) |
| Sync | soft_correlation |
| Provenance | physically_validated_configuration (not universal) |

Validation notes (state trial counts):

* **3/3** CRC-valid at 70 ms (`DEMO_DEMO_334`, 3000/8000, CPFSK)
* Earlier **8/10** at 120 ms (3500/7500, CPFSK, remote TX → local mic)
* **2/3** at 40 ms (aggressive; not default)
* Near-US physical decode **not reliable** on tested hardware

## Recommended live commands

```bash
# Reliable audible (historical strong point)
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message DEMO-LAB-2027 --modulation cpfsk \
  --symbol-duration 0.12 --frequency-zero 3500 --frequency-one 7500 \
  --repeats 2 --amplitude 0.28

# Fast audible (conference timing)
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message DEMO_DEMO_334 --modulation cpfsk \
  --symbol-duration 0.07 --frequency-zero 3000 --frequency-one 8000 \
  --repeats 1 --amplitude 0.30
```

Same-host:

```bash
python -m src.stage_demo --live --message DEMO_DEMO_334 --modulation cpfsk \
  --config configs/conference-audible-demo.yaml
```

## Verified physical replay

```bash
python -m src.replay --input-wav output/samples/replay/rx.wav
# or
python -m src.stage_demo --replay output/samples/replay/rx.wav
```

## Simulation rehearsal

```bash
python -m src.stage_demo --simulate --message DEMO-LAB-2027 --modulation cpfsk
python -m src.stage_demo --wizard   # interactive; choose SIMULATION / LIVE / REPLAY
```

## Campaign pointers

| Campaign | Trials | Result |
| --- | --- | --- |
| Remote audible 120 ms | 10 | 8/10 CRC VALID |
| Remote + Hamming HELLO | 4 | 4/4 CRC VALID |
| Fast 70 ms DEMO_DEMO_334 | 3 | 3/3 CRC VALID |
| Fast 40 ms | 3 | 2/3 CRC VALID |
| Near-US physical calibration | sweep | failure / weak SNR |

Full rows: `docs/results-summary.md`.
