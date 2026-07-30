# Conference runbook — acoustic-channel-poc

Authorized educational demonstration only. Synthetic payloads via CLI.

## Equipment checklist

- Presenter laptop (TX) with working speakers
- Capture host with microphone (USB or Rear Mic)
- Optional: remote TX via SSH (`nkn@192.168.68.109` / `t11`)
- Quiet room; disable mic monitoring if possible (manual OS settings)
- Pre-copied `experiments/` physical capture for replay fallback

## Pre-event calibration (30–45 min)

```bash
cd acoustic-channel-poc && source .venv/bin/activate
python -m src.hardware_profile --redacted
python -m src.calibration --physical --input-device 0 --output-device 0 \
  --start-frequency 2000 --end-frequency 10000 --step 250 \
  --out-dir output/calibration
# Review MOST_RELIABLE recommendation before going live
```

Near-ultrasonic only if response supports it:

```bash
python -m src.calibration --physical --near-ultrasonic \
  --start-frequency 15000 --end-frequency 21000 --step 250 \
  --amplitude 0.10 --out-dir output/calibration-near-us
```

## Room setup

- Mic ~30 cm facing speaker (document distance)
- Analog speaker path preferred over HDMI-only sinks
- Keep amplitude ≤ 0.28; never raise OS volume automatically

## Live monitor

```bash
python -m src.live_monitor --remote-tx nkn@192.168.68.109 \
  --remote-output-device 1 --message DEMO-LAB-2027 --modulation cpfsk
```

Shows waveform sparkline, f0/f1 energy bars, soft bits, sync/CRC, recovered message.

## Four-minute narrative

1. Isolated laptop, no network requirement for the acoustic path
2. Enter synthetic token (`DEMO-LAB-2027`)
3. Show protocol framing (preamble / sync / CRC)
4. Start acoustic transmitter
5. Spectrum while audience hears little or an audible preview
6. Tone energies + reconstructed bits
7. FEC corrections if enabled
8. CRC VALID + recovered payload
9. Audible frequency-shifted preview (labelled as such)
10. Detection / low-pass mitigation takeaway

## Commands

Stage wizard:

```bash
python -m src.stage_demo --wizard
```

Live remote TX + local RX experiment:

```bash
python -m src.experiment --non-interactive --remote-tx nkn@192.168.68.109 \
  --remote-output-device 1 --message DEMO-LAB-2027 --trials 5 \
  --modulation cpfsk --fec none
```

Replay fallback (must be PHYSICAL_RX capture):

```bash
python -m src.stage_demo --replay experiments/<exp>/trial-001/rx.wav
```

## Failure recovery

1. Retry with profile `reliable` (200 ms, 4/6 kHz)
2. Lower min-ratio / raise mic gain carefully
3. Switch to PHYSICAL CAPTURE REPLAY
4. Never label replay as live; never auto-raise amplitude beyond safety limit

## Safety / shutdown

- Ctrl+C cancels playback/recording
- Leave OS echo-cancellation / AGC settings unchanged by the tool
- Backup `experiments/` and `output/calibration/` before teardown

## Artefact backup

```bash
tar czf acoustic-demo-backup-$(date +%Y%m%d).tgz experiments output/calibration docs/results-summary.md
```
