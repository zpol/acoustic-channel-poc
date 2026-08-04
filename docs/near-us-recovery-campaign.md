# Near-ultrasonic recovery campaign

Authorized laboratory only. Synthetic payloads only.

Goal: push the **existing** TX→RX path as far as practical into the upper band
before declaring near-US impossible on this hardware — then swap hardware if needed.

## Baseline (already measured)

From `output/samples/calibration-near-us-physical/` (PHYSICAL_RX):

| Label | f0 / f1 (Hz) | estimated_detector_snr_db |
| --- | --- | --- |
| MOST_RELIABLE | 15750 / 18000 | ≈ −4.1 |
| BEST_COMPROMISE | 15000 / 16000 | ≈ −6.5 |
| HIGHEST_FREQUENCY | 19750 / 20750 | ≈ −38.7 |

Status: `weak_or_unusable` for live decode on that pair.

Do **not** start recovery at 18500/19500 unless repeating a known-bad baseline.

## Config

Canonical starting point: [`configs/near-us-recovery.yaml`](../configs/near-us-recovery.yaml)

## Trial matrix

| ID | f0/f1 | Tsym | FEC | repeats | N | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| NU-A | 15000/16000 | 0.25 | none | 2 | 5 | Least-bad compromise carriers |
| NU-B | 15750/18000 | 0.25 | hamming74 | 2 | 5 | Calib “most reliable” + FEC |
| NU-C | 15000/16000 | 0.40 | hamming74 | 3 | 5 | Slow / maximum margin |
| NU-D | 18500/19500 | 0.25 | hamming74 | 2 | 3 | Classic pair baseline (expect fail) |

Success metric: **CRC-valid frames / N** (never percentage without N).

Stop-to-hardware rule: if NU-A..C are **0/N** with N≥5 and detector SNR remains negative, proceed to mic/speaker swap ([`docs/alternative-physical-channels.md`](alternative-physical-channels.md)).

## Example commands

```bash
# NU-A
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message HELLO --modulation cpfsk \
  --near-ultrasonic --frequency-zero 15000 --frequency-one 16000 \
  --symbol-duration 0.25 --repeats 2 --amplitude 0.30 --fec none

# NU-B
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message HELLO --modulation cpfsk \
  --near-ultrasonic --frequency-zero 15750 --frequency-one 18000 \
  --symbol-duration 0.25 --repeats 2 --amplitude 0.30 --fec hamming74

# NU-C
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message HELLO --modulation cpfsk \
  --near-ultrasonic --frequency-zero 15000 --frequency-one 16000 \
  --symbol-duration 0.40 --repeats 3 --amplitude 0.30 --fec hamming74
```

Disable mic enhancements (AGC / noise suppression / echo cancellation) when possible.

## Software notes

- Prefer calibration-derived carriers over hard-coded 18.5/19.5 kHz wizard defaults.
- Use production decode path (`decode_from_samples`): soft sync, drift search, soft combining.
- Keep `--near-ultrasonic` mandatory above 17 kHz.

## Results log

Record each session under `experiments/` and copy a redacted summary to
`output/samples/experiment-summaries/` before publication.

| Date | Campaign ID | Git | N | CRC-valid | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-08-04 | NU-A HELLO | local | 1 | 1/1 | 15/16 kHz, 0.25s, hamming74×2 |
| 2026-08-04 | NU payloads | local | 4+1 | 5/5 CRC; 4/4 exact after SSH quote fix | `output/lab_nearus_payloads/`; first `p4$$w0rd` hit remote `$$` expansion |
