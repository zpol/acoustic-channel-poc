# Experiment methodology

## Threat model (demo scope)

Air-gapped educational channel: synthetic text → acoustic modulation → speaker → room → microphone → decode. No credentials, files, clipboard, network exfil, persistence, or remote control.

## Provenance labels

| Label | Meaning |
|-------|---------|
| GENERATED_TX | Synthesized transmit waveform |
| SIMULATED_RX | Synthetic channel impairments |
| PHYSICAL_RX | Real microphone capture |
| PHYSICAL_REPLAY | Decode of a prior PHYSICAL_RX WAV |

Never present SIMULATED_RX as PHYSICAL_RX.

## Metrics vocabulary

- **estimated_detector_snr_db**: Goertzel tone energy vs gap/noise estimate. Not calibrated SPL.
- **audible_leakage_ratio_db**: Energy below a configurable threshold (default 17 kHz) relative to carrier-band energy. Not a human hearing test.

## Protocol layers

1. Framing: preamble + sync + version + length + payload + CRC-16-CCITT
2. Optional FEC: Hamming(7,4) on body after preamble+sync (`--fec hamming74`)
3. Modulation: legacy BFSK or continuous-phase CPFSK
4. Detection: Goertzel (± optional frequency neighbourhood)
5. Sync: legacy exact match or correlation with Hamming tolerance
6. Integrity: CRC after FEC decode

## Physical procedure

1. Hardware profile (redacted)
2. Ambient noise
3. Latency pilot + cross-correlation
4. Frequency calibration package
5. Carrier recommendations (MOST_RELIABLE / HIGHEST_FREQUENCY / BEST_COMPROMISE)
6. N trials with raw WAV retained (including failures)
7. Summary JSON/MD/CSV under `experiments/<timestamp>-…/`
