# Part 3 — near-us-fast vs ggwave-like spectral efficiency

**Question:** Would switching to a multi-tone FSK stack similar to [ggwave](https://github.com/ggerganov/ggwave) increase practical speed on this laptop path?

**Short answer:** Yes on **raw bitrate** in theory (~one order of magnitude). On **this** near-US laptop path, PHYSICAL_RX A/B showed ggwave ultrasound **0/5** vs near-us-fast **5/5** — so **no practical speed win** here until a multi-tone path actually decodes.

Provenance in this note:

- Analytic / documented upstream rates: **not PHYSICAL_RX**
- Lab A/B results (when present): **PHYSICAL_RX** under `output/part3/ggwave-bench/`

## Mechanism difference

| | `configs/near-us-fast.yaml` (this repo) | ggwave (upstream docs) |
| --- | --- | --- |
| Modulation | Binary CPFSK — **1 tone at a time** | Multi-FSK — data in 4-bit chunks; **6 simultaneous tones** → **3 bytes per TX slot** |
| Near-US carriers | 15000 / 16000 Hz | Ultrasonic protocols use `F0 ≈ 15000 Hz`, `dF ≈ 46.875 Hz`, ~4.5 kHz occupied band |
| Typical raw rate | `1/0.12 ≈ 8.3 bit/s` | Documented **~8–16 bytes/s** ≈ **64–128+ bit/s** (Normal / Fast / Fastest) |
| `HELLO` (5 B) ideal airtime | ~12.5 s (104 framed bits × 0.12 s) | Order **~0.5–2 s** of payload+ECC (protocol-dependent), not ~12 s |

ggwave splits payload into nibbles and places six tones in parallel across a dense frequency grid. That is a **spectral-efficiency** play, not a shorter binary symbol alone.

## Where a gain is expected

- More information bits per second of airtime (frequency parallelism).
- Shorter wall-clock for short synthetic payloads (the PoC regime).
- Built-in ECC may replace slow Hamming×repeats when the multi-tone decoder works.

## Where a gain may vanish on *this* hardware

- Part 2 calibration showed **weak / negative** `estimated_detector_snr_db` across 15–21 kHz on the tested path. Six concurrent near-US tones need more SNR and linearity than two slow carriers.
- Laptop speakers + AGC / noise suppression can smear bins spaced ~47 Hz apart.
- Large payloads remain impractical: even ×10–×20 vs near-us-fast, **1 MiB** is still on the order of **days**, not minutes.

## Idealized transfer-time comparison (not Shannon; not a lab claim)

Assumptions: FER=0; near-us-fast framing as implemented; ggwave useful rate ≈ **10 B/s** (low end of the published 8–16 B/s band, ECC included).

| Payload | near-us-fast (ideal) | ggwave ~10 B/s (ideal) |
| --- | --- | --- |
| 1 B | ~8.6 s | ≪ 1 s (+ markers) |
| 10 B | ~17 s | ~1–2 s |
| 100 B | ~2 min | ~10–20 s |
| 1000 B | ~18 min | ~2–3 min |
| 1 MiB | ~13 days | ~1–1.5 days |

## Publication rule

Do **not** claim “ggwave is N× faster on this lab pair” without a PHYSICAL_RX A/B campaign stating **M/N**, airtime, and payload goodput.

## Measured A/B (this lab, 2026-08-06)

See [`part3-ggwave-bench.md`](part3-ggwave-bench.md).

| Stack | HELLO N=5 | FER | Goodput |
| --- | --- | --- | --- |
| ggwave ultrasound p3 / p5 | 0/5 | 1.0 | 0 |
| near-us-fast | **5/5** | 0.0 | ~3.2 bit/s |

**Decision:** keep binary near-us-fast; do not adopt ggwave as the near-US production path based on this evidence.

Full design, CSV paths, and follow-ups: [`part3-ggwave-bench.md`](part3-ggwave-bench.md).
