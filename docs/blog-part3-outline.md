# Part 3 article outline — Measuring Acoustic Channel Capacity

Working title:

> **No Network Required, Part 3: How Fast Can a Laptop Acoustic Channel Go Before Physics Says No?**

Central question:

> How fast can this acoustic channel become before physics—and ordinary laptop hardware—become the limiting factor?

## 1. Hook

Part 1 proved audible CRC-valid frames. Part 2 showed near-US theory failing calibration, then recovering with a slow profile. Part 3 asks for **measured capacity**, not vibes.

## 2. What “capacity” means here

Define measured metrics only:

- raw symbol rate `1/Tsym`
- payload goodput (payload bits × successes / total airtime)
- FER, BER
- latency / airtime
- CPU decode cost

Explicitly refuse Shannon-capacity claims.

## 3. Protocol under test

Summarize frame, sync, CPFSK/BFSK, FEC, repeats (link `docs/part3-protocol-summary.md`).

Show overhead figure: raw rate vs goodput for `HELLO`.

## 4. Experimental design

- Hypotheses per axis (Tsym, spacing, modulation, redundancy, compression)
- Controlled vs measured variables
- SIMULATED_RX campaigns for mechanism
- PHYSICAL_RX validation campaign (authorized lab) with stated N

## 5. Results — simulation

Insert Part 3 figures (`output/part3/figures/`), labelled SIMULATED_RX:

- Tsym mild impairment
- Tsym harsh cliff (if FER rises)
- spacing
- BFSK vs CPFSK
- FEC vs repeats
- compression table

Explain **why** goodput can fall when raw rate rises (FER × airtime).

## 6. Results — physical priors + new campaign

Cite prior PHYSICAL_RX counts only as documented:

- 70 ms: 3/3
- 40 ms: 2/3
- 50–60 ms initial sweep failures
- Near-US recovery: slow but CRC VALID

Present any new physical Part 3 trials with full provenance.

## 7. Ranked improvements

Publish the ranked list from the technical report (measure first, then change).

## 8. What did not help

- Payload zlib for short text / JSON / random (often expands under 32 B cap)
- Blind repeats+FEC when channel is already clean (airtime tax)
- M-ary without a new demodulator (not yet production)

## 9. Recommended operating points

- Conference / demo: existing audible 70 ms profile
- Aggressive audible candidate for physical re-test: see `configs/part3-best-candidate.yaml`
- Near-US: keep recovery profile; do not confuse with capacity maximization

## 10. Closing

The limit is not “Python is slow”. It is transducers, room, sync margin, and frame overhead. Faster is only better when goodput rises.
