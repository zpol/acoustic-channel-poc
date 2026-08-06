# Part 3 — Current protocol technical summary

Repository: `acoustic-channel-poc`  
Scope: implementation as of Part 3 capacity work.  
Provenance vocabulary: `GENERATED_TX` / `SIMULATED_RX` / `PHYSICAL_RX`.

## Frame structure

Defined in `src/protocol.py`.

| Field | Size | Notes |
| --- | --- | --- |
| Preamble | 16 bits | `1010…` |
| Sync word | 16 bits | `0xA5F0` |
| Version | 8 bits | `0x01` |
| Payload length | 8 bits | 1–64 bytes |
| Payload | `8 × N` bits | UTF-8 synthetic text |
| CRC-16-CCITT | 16 bits | Over version ‖ length ‖ payload |

Repeats are **not** inside the bit frame. The transmitter may emit the framed waveform 1–3 times with inter-frame silence (`modulate_*`).

## Synchronization

Preferred production path (`live_monitor`, capacity campaigns): soft energy preamble correlation (`sync_mode=correlation`).

Also present: legacy exact match and Hamming-tolerant hard correlation.

Latency chirp calibration exists for timing measurement only; it is not the modem sync word.

## Modulation

Binary FSK only (`src/modulation.py`):

- **BFSK**: independent per-symbol tones with short fades
- **CPFSK**: continuous phase across symbols

One bit per symbol. No M-ary / PSK / OFDM in the production decoder.

## Carrier frequencies & symbol duration

| Profile | f0 / f1 | Tsym | Notes |
| --- | --- | --- | --- |
| Code defaults | 3500 / 7500 Hz | 0.12 s | `ModulationConfig` |
| Conference audible | 3000 / 8000 Hz | 0.07 s | `configs/conference-audible-demo.yaml` |
| Near-US recovery | 15000 / 16000 Hz | 0.25 s | `configs/near-us-recovery.yaml` + FEC |

## FEC & redundancy

- Optional **Hamming(7,4)** on body after preamble+sync (`src/fec.py`)
- CRC remains the trust decision after FEC
- Frame repeats (1–3) with optional soft log-energy combining on RX
- Interleaver helpers exist but are **not** wired into encode/decode

## Timing recovery

1. Symbol-phase grid search over one symbol period
2. Bounded symbol-duration search (± percent, discrete steps)
3. Optional carrier neighbourhood Goertzel search

No continuous PLL.

## Decoder pipeline

`receiver.decode_from_samples`:

samples → optional bandpass → timing/Tsym candidates → Goertzel demod → soft/hard bits → soft sync → optional soft combine → FEC → CRC → recovered payload (+ optional BER vs expected bits)

## Implications for capacity

For payload `HELLO` (5 B) without FEC:

- framed bits = **104**
- overhead ≈ **61.5%** of coded bits
- ideal payload goodput if always successful ≈ `40 / (104 × Tsym)` bit/s (no repeats)

Example: Tsym=70 ms → airtime ≈ 7.28 s → ideal goodput ≈ **5.5 bit/s**.

With Hamming(7,4): 165 coded bits → more airtime → lower goodput unless it prevents enough frame losses to compensate.
