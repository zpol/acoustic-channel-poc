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

Status (calib package): `weak_or_unusable` for treating the raw sweep as a robust modem band.

Do **not** start recovery at 18500/19500 unless repeating a known-bad baseline.

**Update (2026-08-04):** a slow recovery profile on **15000/16000 Hz** recovered CRC-valid PHYSICAL_RX frames (see Results log). That does **not** rewrite the calib SNR curve; it shows negative calib SNR ≠ “impossible under every profile”.
## Config

Canonical starting point for **margin**: [`configs/near-us-recovery.yaml`](../configs/near-us-recovery.yaml)  
Canonical starting point for **speed** (lab-validated): [`configs/near-us-fast.yaml`](../configs/near-us-fast.yaml)

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
| 2026-08-06 | NU-fast cliff HELLO | local | 7 | 7/7 | 15/16 kHz; Tsym 0.12–0.25; FEC none/hamming; R=1–2 — see `output/part3/physical/nearus_speed_probe.log` |
| 2026-08-06 | NU-fast Quixote | local | 1 | 1/1 | 59 B sentence @ 0.12s/none/R1; airtime ≈64 s; payload goodput ≈7.3 bit/s |

### Fast profile (recommended when FER stays low)

`live_monitor` shows tone energy live; the recovered plaintext appears **after** capture via **blind CRC decode** (RX does not need prior knowledge of the payload). Wait for the RESULT panel — do not Ctrl+C during “Blind CRC decode…”.

Lab-validated command (PHYSICAL_RX, amp **0.18** worked for a 38 B synthetic payload when 0.30 hit CRC mismatch / hot peak):

```bash
# On RX PC only — SSH starts TX. Placeholders: demo-user@tx-host, outdev 0.
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 0 --input-device 0 \
  --message HELLO --modulation cpfsk \
  --near-ultrasonic --frequency-zero 15000 --frequency-one 16000 \
  --symbol-duration 0.12 --repeats 1 --amplitude 0.18 --fec none
```

If CRC fails with peak ≫ 0.3, lower `--amplitude` (try 0.18) or speaker volume before raising FEC/repeats.

Config: [`configs/near-us-fast.yaml`](../configs/near-us-fast.yaml) (YAML still lists amp 0.30 as the nominal profile). Fall back to the 0.25 s + Hamming ×2 recovery profile if the path degrades.

See also ggwave ultrasound A/B (negative on this path): [`part3-ggwave-bench.md`](part3-ggwave-bench.md).
