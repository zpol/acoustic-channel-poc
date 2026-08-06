# Part 3 physical capacity cliff — campaign checklist

Authorized lab only. Synthetic payloads only. SSH may coordinate playback; payload travels acoustically.

## Hypothesis

Under PHYSICAL_RX, payload goodput peaks at an intermediate Tsym: shorter than 120 ms but longer than the region where FER collapses (historically near 40–70 ms on this hardware).

## Fixed parameters

```text
Modulation: CPFSK
f0/f1:      3000 / 8000 Hz
FEC:        none
Repeats:    1
Silence:    0.0 s
Amplitude:  0.28
Payload:    DEMO_DEMO_334
Bandpass:   off
Sync:       correlation
```

## Sweep

| Tsym (ms) | N | Record |
| --- | --- | --- |
| 120 | ≥10 | WAV + log |
| 80 | ≥10 | WAV + log |
| 70 | ≥10 | WAV + log |
| 50 | ≥10 | WAV + log |
| 40 | ≥10 | WAV + log |
| 30 | ≥10 | WAV + log |

## Metrics to compute

Use `src.capacity_metrics` / Part 3 CSV schema:

- successes M/N
- FER
- payload goodput
- mean airtime
- sync vs CRC failure counts

## Success criterion for updating the “best candidate”

A faster point may replace 70 ms in `configs/part3-best-candidate.yaml` only if:

1. FER ≤ 0.2 with N≥10, and
2. payload goodput strictly exceeds the 70 ms condition on the same day/setup, and
3. provenance is PHYSICAL_RX with hashes retained.

## Example command family

```bash
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message DEMO_DEMO_334 --modulation cpfsk \
  --frequency-zero 3000 --frequency-one 8000 \
  --symbol-duration 0.07 --repeats 1 --amplitude 0.28 --fec none
```

Repeat across Tsym values; do not cherry-pick successes without counting failures.
