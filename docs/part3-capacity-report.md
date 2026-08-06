# Part 3 technical report — Measuring practical capacity of the laptop acoustic channel

**Project:** No Network Required / `acoustic-channel-poc`  
**Date:** 2026-08-06  
**Question:** What is the *practical* information capacity of this speaker→microphone path under the current protocol?

This report does **not** claim Shannon capacity. All rates are measured.

Provenance:

- Simulation campaigns: **SIMULATED_RX** (`output/part3/`)
- Prior lab results cited for context: **PHYSICAL_RX** (existing campaign docs only)

Reproduce:

```bash
PYTHONPATH=. python scripts/part3/run_capacity_campaigns.py --trials 12 --seed 20260806
PYTHONPATH=. python scripts/part3/generate_part3_figures.py
```

---

## 1. Protocol under test (summary)

See [`docs/part3-protocol-summary.md`](part3-protocol-summary.md).

Binary CPFSK/BFSK, soft-energy sync, optional Hamming(7,4), CRC-16 trust decision, optional frame repeats.

For payload `HELLO` (5 bytes), FEC none:

| Quantity | Value |
| --- | --- |
| Payload bits | 40 |
| Framed bits | 104 |
| Overhead fraction | 0.615 |
| Ideal goodput @ 70 ms if always OK | ≈ 5.49 bit/s |
| Raw symbol rate @ 70 ms | ≈ 14.29 baud (= bit/s for binary FSK) |

Figures: `output/part3/figures/fig-overhead-raw-vs-goodput.*`

---

## 2. Metrics

| Metric | Definition |
| --- | --- |
| Raw symbol rate | `1 / Tsym` (bits/s for 1 bit/symbol) |
| Payload goodput | `8 × payload_bytes × successes / Σ airtime` |
| FER | `1 − successes/N` (exact payload match + CRC VALID) |
| BER | Bit disagreements vs expected framed bits when known |
| Airtime | Includes coded bits × Tsym + repeats + inter-frame silence |
| Decode CPU | Wall time inside `decode_from_samples` |

Success criterion for a trial: recovered string equals intended payload.

---

## 3. Experimental design

### 3.1 Simulation campaigns (this report)

| Campaign | Hypothesis | Controlled | Measured | N/condition |
| --- | --- | --- | --- | --- |
| `tsym` | Shorter Tsym raises goodput until errors appear | Tsym, mild noise | FER, BER, goodput, CPU | 12 |
| `cliff` | Harsh AWGN+attenuation creates a short-Tsym cliff | Tsym, noise, attenuation | FER, BER, goodput | 12 |
| `spacing` | Carrier spacing affects discrimination | f0/f1 pairs @ 70 ms | FER, goodput | 12 |
| `modulation` | CPFSK vs BFSK differs under same impairment | modulation, Tsym | goodput, FER | 12 |
| `redundancy` | FEC/repeats trade airtime for reliability | fec, repeats | FER, goodput | 12 |
| `overhead` | Analytic frame tax | payload, fec, Tsym, repeats | ideal goodput | analytic |
| `compression` | zlib helps end-to-end under 32 B cap | payload class | ratio, CPU | microbench |

Seed: `20260806`. Manifest: `output/part3/campaign_manifest.json`.

### 3.2 Physical priors (already documented; not re-invented)

| Evidence | Result | Provenance |
| --- | --- | --- |
| Audible 70 ms, 3000/8000, `DEMO_DEMO_334` | **3/3** CRC VALID | PHYSICAL_RX |
| Audible 40 ms, same carriers | **2/3** | PHYSICAL_RX |
| Audible 50–60 ms initial sweep | failures in that sweep | PHYSICAL_RX |
| Near-US recovery 15/16 kHz, 250 ms, Hamming×2 | HELLO **1/1**; payloads **5/5** CRC / **4/4** exact after quote fix | PHYSICAL_RX |

Physical channel is **harsher** than mild AWGN simulation: usable fast region sits nearer **40–70 ms**, not 20 ms.

### 3.3 Physical campaign still required (Part 3 validation)

A dedicated PHYSICAL_RX cliff sweep (Tsym ∈ {120,80,70,50,40,30} ms, N≥10 each) remains the publication gate for any claim that beats the 70 ms conference point.

---

## 4. Results — SIMULATED_RX

### 4.1 Mild Tsym sweep

Under mild impairment, FER stayed ~0 down to 30 ms and goodput tracked `1/Tsym` after overhead.  
Figure: `fig-tsym-fer-goodput`.

**Interpretation:** AWGN-only sims can overstate how short Tsym may go. They are useful for overhead accounting, not for declaring physical limits.

### 4.2 Harsh cliff sweep

Selected slice (`noise=0.10`, `attenuation=0.10`, CPFSK, FEC none, R=1, `HELLO`):

| Tsym | FER | Mean BER | Payload goodput (bit/s) | Successes |
| --- | --- | --- | --- | --- |
| 20 ms | **0.25** | 0.020 | 14.42 | 9/12 |
| 30 ms | 0.00 | 0.000 | 12.82 | 12/12 |
| 40 ms | 0.00 | 0.000 | 9.62 | 12/12 |
| 50 ms | 0.00 | 0.000 | 7.69 | 12/12 |
| 70 ms | 0.00 | 0.000 | 5.49 | 12/12 |
| 80 ms | 0.00 | 0.000 | 4.81 | 12/12 |
| 120 ms | 0.00 | 0.000 | 3.21 | 12/12 |

Figure: `fig-cliff-fer-goodput`.

Observations:

1. Errors appear first at **20 ms** in this impairment model.
2. Even with FER=0.25, goodput at 20 ms can still exceed 30 ms — failures are not free, but airtime savings can dominate until FER grows further.
3. Therefore the objective must be **goodput under a FER constraint**, not raw baud.

Under a constraint FER ≤ 0.20 on this slice, **30 ms** is preferred to 20 ms.

### 4.3 Carrier spacing

At 70 ms / mild noise, spacings from 1 kHz to 8 kHz all achieved FER=0 and identical goodput (5.49 bit/s) in this AWGN model.

**Interpretation:** spacing effects on *this* Goertzel binary FSK stack are not resolved by mild AWGN; physical frequency response (calib curves) matters more. Ranking physical carriers still belongs to calibration + live trials.

### 4.4 BFSK vs CPFSK

No goodput difference in these SIMULATED_RX conditions (both FER=0 at tested Tsym).

Prior GENERATED_TX work already showed CPFSK is not automatically “quieter” in audible leakage. Prefer CPFSK for continuous-phase implementation reasons, not sim goodput.

### 4.5 FEC vs repeats (stressed but still easy channel)

In the redundancy campaign as configured, all variants succeeded; **goodput fell** as FEC expansion and repeats increased airtime:

| Config | Goodput (bit/s) |
| --- | --- |
| none, R=1 | 7.69 |
| hamming74, R=1 | 4.85 |
| none, R=2 + 0.25 s silence | 3.76 |
| hamming74, R=2 + silence | 2.39 |

**Interpretation:** redundancy is an insurance premium. It pays when FER would otherwise be high (near-US recovery story). It hurts when the channel is already clean.

### 4.6 Compression

zlib on representative payloads (`output/part3/compression_eval.csv`):

| Payload class | Ratio (out/in) | Worthwhile under 32 B cap? |
| --- | --- | --- |
| short text `HELLO` | 2.60 (expands) | No |
| email-like | 1.53 (expands) | No |
| JSON (38 B) | 1.13 (expands) | No |
| random 32 B | 1.25 (expands) | No |
| repetitive 32×`A` | **0.34** | Yes (toy case) |

**Conclusion:** for the synthetic short payloads this protocol carries, compression usually **does not** improve end-to-end throughput and often expands. Do not add compression to the hot path without a length+CRC framing redesign.

### 4.7 Multiple bits per symbol / alternate modulations

Not implemented in the production decoder (still 1 bit/symbol binary FSK).

Design note for later work:

- 4-FSK could raise raw rate at fixed Tsym, but needs four tones, new decision regions, and likely longer symbols or higher SNR to keep symbol error rate acceptable.
- Until a demodulator exists, any M-ary claim is unsupported.
- Priority remains characterizing binary FSK goodput vs Tsym on PHYSICAL_RX.

---

## 5. Ranked protocol improvements

Ranked by expected **measured goodput benefit / evidence / complexity**:

| Rank | Change | Why | Evidence status | Complexity |
| --- | --- | --- | --- | --- |
| 1 | **Measure goodput, not baud** in all future trials | Prevents false “faster” claims | Implemented in Part 3 harness | Low |
| 2 | **Physical Tsym cliff campaign** (N≥10) around 40–70 ms | Aligns publishable limit with hardware | PHYSICAL priors exist; larger N pending | Medium (lab time) |
| 3 | Keep **70 ms / 3–8 kHz CPFSK** as conference default | Best *evidenced* fast audible point (3/3) | PHYSICAL_RX | None |
| 4 | Use **FEC+repeats only when FER demands it** | Near-US recovery succeeded this way; clean audible pays an airtime tax | PHYSICAL_RX + sim | Low |
| 5 | Reduce **inter-frame silence** when repeats=1 | Silence is pure goodput loss | Analytic | Low |
| 6 | Optional: trim idle capture tails in live tooling | Latency/CPU, not PHY rate | Engineering | Low |
| 7 | Carrier retune from **physical calib**, not sim spacing sweeps | Mild AWGN spacing sweeps were uninformative | PHYSICAL calib | Medium |
| 8 | Consider M-ary / multi-bit **only after** binary cliff is mapped physically | Explainability first | Not implemented | High |
| 9 | Payload compression | Not worthwhile for ≤32 B synthetic text | Microbench | Low (skip) |

---

## 6. Best-performing candidate (code + config)

Config: [`configs/part3-best-candidate.yaml`](../configs/part3-best-candidate.yaml)

Choice for **publication-facing** operation:

- CPFSK, **3000/8000 Hz**, **Tsym=70 ms**, FEC none, repeats=1  
- Rationale: maximizes *evidenced* physical reliability among fast audible points; sim “20 ms winners” are **not** promoted to physical claims.

Harness / metrics code:

- `src/capacity_metrics.py`
- `scripts/part3/run_capacity_campaigns.py`
- `scripts/part3/generate_part3_figures.py`

---

## 7. Limitations

1. Mild AWGN simulation underestimates physical multipath, AGC, non-flat response, and clock issues.
2. HELLO-only sim payloads; longer frames change overhead ratios.
3. FER confidence intervals are wide at N=12 (Wilson shown in CSV).
4. No Shannon / mutual-information estimator.
5. M-ary not implemented — listed as future work, not a result.

---

## 8. Answers to the research axes

| Axis | Finding |
| --- | --- |
| Shorter symbols | Sim cliff emerges near ~20 ms under harsh AWGN; physical priors place the practical cliff nearer **40–70 ms**. |
| Carrier spacing | Unresolved in mild sim; defer to physical calib/response. |
| Alternate modulation | Binary BFSK≈CPFSK in these sims; keep CPFSK. |
| Multi-bit symbols | Not yet; do not claim benefit. |
| Frame overhead | Dominant: ~61% for HELLO without FEC; goodput ≪ raw rate. |
| Error correction | Helps stressed channels; taxes clean channels. |
| Compression | Generally not worthwhile for this payload regime. |
| Channel capacity | Report **payload goodput + FER + N**; e.g. ideal HELLO @70 ms ≈ 5.5 bit/s if always successful; physical success rate must multiply. |

---

## 9. Deliverables checklist

| Deliverable | Path |
| --- | --- |
| Protocol summary | `docs/part3-protocol-summary.md` |
| This report | `docs/part3-capacity-report.md` |
| Article outline | `docs/blog-part3-outline.md` |
| Benchmark suite | `scripts/part3/run_capacity_campaigns.py` |
| Figures | `output/part3/figures/` |
| Best candidate config | `configs/part3-best-candidate.yaml` |
| Result tables | `output/part3/*.csv`, `best_candidate_sim.json` |
