# Part 3 — PHYSICAL_RX A/B: near-us-fast vs ggwave ultrasound

Authorized laboratory only. Synthetic payloads only.

## Hypothesis

A ggwave-like multi-tone ultrasonic stack delivers higher **payload goodput** than binary `near-us-fast` on the same laptop speaker→microphone path.

## Design

| Item | Value |
| --- | --- |
| Payload | `HELLO` |
| N per stack | **5** |
| Baseline | `configs/near-us-fast.yaml` — CPFSK 15/16 kHz, Tsym 0.12 s, FEC none, R=1 |
| Challenger | Python `ggwave` ultrasound protocols **3** (`[U] Normal`) and **5** (`[U] Fastest`) |
| TX | remote lab host via SSH playback coordination only |
| RX | local microphone, `PHYSICAL_RX` |
| Metrics | successes M/N, FER, airtime, payload goodput |
| Script | [`scripts/part3/ggwave_physical_bench.py`](../scripts/part3/ggwave_physical_bench.py) |

Reproduce:

```bash
source configs/local-lab.env
pip install ggwave   # optional dependency for this bench
PYTHONPATH=. python scripts/part3/ggwave_physical_bench.py \
  --trials 5 --payload HELLO --ggwave-protocols 3,5 --stacks both
```

Outputs: `output/part3/ggwave-bench/{all_trials.csv,summary.csv,manifest.json,run.log}` (WAVs gitignored). Lab hostnames redacted in tracked `run.log`.

## Results (2026-08-06)

Provenance: **PHYSICAL_RX**

| Stack | N | CRC/exact OK | FER | Mean airtime (s) | Payload goodput (bit/s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| ggwave ultrasound p3 (Normal) | 5 | **0/5** | 1.00 | 2.90 | 0 |
| ggwave ultrasound p5 (Fastest) | 5 | **0/5** | 1.00 | 1.88 | 0 |
| near-us-fast | 5 | **5/5** | 0.00 | 12.48 | **3.21** |

Notes:

- ggwave TX waveforms were generated and played (`PLAY_DONE`); RX peaks were often low (~0.01–0.25). Decoder returned no payload (`no_decode`) on all ultrasound trials.
- Digital loopback of the same ggwave encode→decode path succeeds in software; the failure mode is the **physical near-US multi-tone path**, consistent with Part 2 weak calib response.
- near-us-fast remained reliable at ~**6–7× longer** airtime than ggwave’s *ideal* TX duration — but with **usable** goodput.

## Decision

**Do not** replace the production modem with ggwave, and **do not** integrate ggwave as a default backend based on this campaign.

| Option | Verdict |
| --- | --- |
| Rewrite `modulation.py` to dense multi-tone FSK | **Rejected for now** — no PHYSICAL_RX success on ultrasound protocols tested |
| Optional ggwave backend | **Not justified** until a protocol/path shows M/N > 0 with competitive goodput |
| Keep `near-us-fast` | **Retain** as the evidenced near-US speed profile |
| Keep `near-us-recovery` | **Retain** as margin fallback |

Theoretical ggwave rates (~8–16 B/s) remain a valid **hypothesis** for other hardware or audible bands; on **this** near-US laptop pair, spectral densification did not yield a working faster channel in N=5.

## Follow-ups (out of scope unless new evidence)

1. Audible-band ggwave A/B (protocols 0–2) — separate campaign; not a substitute for near-US claims.
2. Calibrate which ultrasonic bins actually radiate on this TX before retrying multi-tone.
3. If a future PHYSICAL_RX multi-tone campaign succeeds, revisit an *explainable* multi-tone prototype in-repo (not a black-box dependency alone).
