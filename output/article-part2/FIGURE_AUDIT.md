# Part 2 Figure Audit

Generated: 2026-08-04T19:43:46.219897+00:00
Git HEAD (at generation): 8bdc9be3b125c65d9d8ad67e98ef5f31b2216eab

| Figure | Description | Status | Evidence source | Provenance | Can generate now | Missing requirement |
| --- | --- | --- | --- | --- | --- | --- |
| FIG-01 | Audible vs near-US calibration | GENERATED_FROM_REAL_DATA | output/samples/calibration-audible-physical/measurements.csv; output/samples/calibration-near-us-physical/measurements.csv; output/article/14-audible-vs-near-us-calibration.png | PHYSICAL_RX | yes | Not calibrated SPL |
| FIG-02 | Generated 18.5/19.5 kHz versus physical recording | MISSING_PHYSICAL_EVIDENCE | output/samples/near_us_HELLO_tx.wav | GENERATED_TX | partial | Record PHYSICAL_RX while playing a documented 18500/19500 TX (or save metadata linking TX+RX hashes), then regenerate FIG-02 |
| FIG-03 | Physical response 15–21 kHz | GENERATED_FROM_REAL_DATA | output/samples/calibration-near-us-physical/measurements.csv | PHYSICAL_RX | yes | Calib SNR does not by itself prove later CRC-valid live decode |
| FIG-04 | Carrier-neighborhood receiver search | GENERATED_FROM_REAL_DATA | configs/near-us-recovery.yaml; docs/near-us-recovery-campaign.md | diagram | yes | Diagram is explanatory; envelope is illustrative, not measured energy from a WAV |
| FIG-05 | First HELLO physical recovery | GENERATED_FROM_REAL_DATA | output/article-part2/evidence/hello_nua_terminal_redacted.log; output/lab_nua_HELLO_20260804T195738.wav | PHYSICAL_RX | yes | Single documented trial in preserved log (N=1 for this HELLO capture) |
| FIG-06 | Exact recovered payloads | GENERATED_FROM_REAL_DATA | output/lab_nearus_payloads/20260804T200528_user@domain.tld_.wav; output/lab_nearus_payloads/20260804T201103_demo_sinclair_2000_.wav; output/lab_nearus_payloads/20260804T201521_this_is_working!!!_.wav | PHYSICAL_RX | yes | Trial counts are the documented runs in summary.md / WAVs (not a large-N study) |
| FIG-07 | Shell quoting bug | GENERATED_FROM_REAL_DATA | output/lab_nearus_payloads/results_20260804T200144.md; src/live_monitor.py; src/experiment.py | PHYSICAL_RX | yes | Diagram summarizes documented outcomes; exact PID value comes from that trial's recovered string |
| FIG-08 | Successful physical spectrogram (HELLO) | GENERATED_FROM_REAL_DATA | output/lab_nua_HELLO_20260804T195738.wav | PHYSICAL_RX | yes | Spectrogram excerpt timing is approximate (not sample-accurate frame bounds) |
| FIG-09 | Experimental architecture | GENERATED_FROM_REAL_DATA | docs/near-us-recovery-campaign.md | diagram | yes | Schematic; not a photograph of the lab setup |
| FIG-10 | Nyquist versus physical chain | GENERATED_FROM_REAL_DATA | docs/blog-part2-nyquist-meets-hardware.md | diagram | yes | Conceptual diagram |
| FIG-11 | Frame and channel pipeline | GENERATED_FROM_REAL_DATA | src/protocol.py; src/fec.py; src/modulation.py | diagram | yes | Schematic |
| FIG-12 | Recovery timeline | GENERATED_FROM_REAL_DATA | docs/near-us-recovery-campaign.md; output/samples/experiment-summaries/20260804-nearus-payloads/summary.md | PHYSICAL_RX | yes | No wall-clock timestamps beyond filenames/summary date 2026-08-04 |

## Regeneration

```bash
cd acoustic-channel-poc
PYTHONPATH=. python scripts/article/generate_part2_figures.py
# or one figure:
PYTHONPATH=. python scripts/article/generate_part2_figures.py --figure FIG-03
```

Outputs land under `output/article-part2/`.

## Ready now

| ID | Files | Notes |
| --- | --- | --- |
| FIG-01 | `figures/fig01-audible-vs-near-us-calibration.{png,svg}` | Metric = `estimated_detector_snr_db` |
| FIG-03 | `figures/fig03-physical-frequency-response-15k-21k.{png,svg}` | PHYSICAL_RX calib |
| FIG-04 | `figures/fig04-carrier-neighborhood-search.{png,svg}` | Explanatory diagram |
| FIG-05 | `figures/fig05-hello-crc-valid-physical-rx.png` | Redacted terminal from log |
| FIG-06 | `figures/fig06-physical-payload-results.{png,svg,csv}` | Documented trials only |
| FIG-07 | `figures/fig07-shell-quoting-before-after.{png,svg}` | Before/after `$$` |
| FIG-08 | `figures/fig08-successful-physical-rx-spectrogram.{png,svg}` | HELLO PHYSICAL_RX |
| FIG-09 | `figures/fig09-experimental-architecture.{png,svg}` | SSH ≠ payload path |
| FIG-10 | `figures/fig10-nyquist-vs-physical-chain.{png,svg}` | Conceptual |
| FIG-11 | `figures/fig11-frame-and-channel-pipeline.{png,svg}` | Conceptual |
| FIG-12 | `figures/fig12-recovery-timeline.{png,svg}` | Order only |

## Generated now

All of the above were produced by `scripts/article/generate_part2_figures.py` from existing CSVs, WAVs, logs, configs, and campaign docs. Original Part-1-era PNG `output/article/14-audible-vs-near-us-calibration.png` was archived as `fig01-source-14-…png` and regenerated with SVG.

## Needs regeneration

None required for label/privacy errors in the new Part-2 pack. Draft prose elsewhere still needs editing (see Unsupported claims).

Optional polish (not blockers):

* FIG-08 frame start/end markers are approximate; improve if a sample-accurate sync offset is logged.
* FIG-05 is a log rendering, not an original screenshot file.

## Missing physical evidence

### FIG-02 — paired GENERATED_TX vs PHYSICAL_RX at 18.5/19.5 kHz

**Status:** `MISSING_PHYSICAL_EVIDENCE`

Only `output/samples/near_us_HELLO_tx.wav` (GENERATED_TX) exists. The near-US calibration `rx_physical.wav` is a frequency **sweep**, not this HELLO frame. Do not pair them.

**Procedure to capture:**

1. On TX (remote or local), play a documented 18500/19500 Hz CPFSK frame of a synthetic payload (e.g. `HELLO`), saving the TX WAV hash.
2. On RX, record the microphone simultaneously into e.g. `output/lab_18500_19500_HELLO_<ISO8601>.wav`.
3. Save metadata JSON linking: TX path + SHA-256, RX path + SHA-256, carriers, Tsym, FEC, amplitude, room notes, `provenance: PHYSICAL_RX`.
4. Optional: attempt decode; CRC may fail — that is still valid evidence for FIG-02 panels.
5. Screenshot or log not strictly required for the spectrogram pair; required if claiming CRC outcome.
6. Validity criterion for the figure: same trial ID for both panels; identical time/frequency axes; provenance labels correct.

**Outputs after capture:**

```text
output/article-part2/figures/fig02-generated-vs-physical-18500-19500.png
output/article-part2/figures/fig02-generated-vs-physical-18500-19500.svg
```

Until then, only the labelled GENERATED_TX reference exists:

```text
figures/fig02-generated-tx-only-18500-19500-NOT-PHYSICAL.{png,svg}
```

## Unsupported claims

Claims in current draft/docs that are **not** supported as written after the 2026-08-04 recovery campaign:

| Source | Claim (paraphrased) | Problem |
| --- | --- | --- |
| `docs/blog-part2-nyquist-meets-hardware.md` ~L210 | Usable ceiling is audible, not near-US | Recovery later obtained CRC VALID at 15/16 kHz with slow symbols + FEC. Calib weakness remains true; “usable ceiling only audible” overstates. |
| Same draft ~L334 | “Part 2 stops at an honest negative for near-US” | Outdated: recovery campaign succeeded for documented payloads. |
| `README.md` / `docs/results-summary.md` | Near-US live decode “not reliable” | Needs nuance: early/default near-US attempts and calib were weak; recovery profile documented successes (not a large-N reliability study). |
| Any implication that calibration negative SNR proves live decode is impossible | Contradicted by HELLO + payload PHYSICAL_RX CRC VALID trials | Keep calib as failure of *that* metric/setup; separate from recovery campaign. |
| FIG-02 as physical proof of 18.5/19.5 behaviour | No paired PHYSICAL_RX | Do not publish as physical evidence. |
| “100% reliable” or large trial counts | Not in evidence | Documented exact matches after quote fix: **4/4** intended strings in the payload campaign summary; HELLO N=1 in preserved log. |

## Publication minimum

| Required | Available? | Status |
| --- | --- | --- |
| FIG-01 | Yes | Ready |
| FIG-03 | Yes | Ready |
| FIG-05 | Yes | Ready |
| FIG-06 | Yes | Ready |
| FIG-08 | Yes | Ready |
| FIG-09 | Yes | Ready |

**Verdict:** publication minimum for Part 2 recovery narrative is met. FIG-02 remains optional and incomplete until a paired 18.5/19.5 PHYSICAL_RX capture exists.
