# Article evidence manifest

Publication inventory for the cybersecurity blog article.
Every item states provenance and what it does **not** demonstrate.

---

## 1. Architecture

**Filename:** `01-architecture.png`  
**Path:** `output/article/01-architecture.png`  
**Provenance:** GENERATED_TX / conceptual  
**Demonstrates:** High-level TX → air → RX pipeline.  
**Does not demonstrate:** Physical link success.  
**Suggested section:** Architecture  
**Suggested caption:** Educational acoustic data-channel architecture.  
**Publication status:** Ready

---

## 2. Protocol frame

**Filename:** `02-frame-format.png`  
**Path:** `output/article/02-frame-format.png`  
**Provenance:** GENERATED_TX / protocol  
**Demonstrates:** PREAMBLE|SYNC|VER|LEN|PAYLOAD|CRC16 layout.  
**Does not demonstrate:** Physical transmission.  
**Suggested section:** Framing and integrity  
**Suggested caption:** On-wire frame format with CRC-16-CCITT.  
**Publication status:** Ready

---

## 3. Generated BFSK spectrum

**Filename:** `03-bfsk-vs-cpfsk-spectrum.png` (left panel)  
**Path:** `output/article/03-bfsk-vs-cpfsk-spectrum.png`  
**Provenance:** GENERATED_TX  
**Demonstrates:** Digital BFSK spectrogram for a synthetic HELLO frame.  
**Does not demonstrate:** Physical speaker response.  
**Suggested section:** Modulation  
**Suggested caption:** Generated BFSK spectrum (synthetic payload).  
**Publication status:** Ready

---

## 4. Generated CPFSK spectrum

**Filename:** `03-bfsk-vs-cpfsk-spectrum.png` (right panel)  
**Path:** `output/article/03-bfsk-vs-cpfsk-spectrum.png`  
**Provenance:** GENERATED_TX  
**Demonstrates:** Digital CPFSK spectrogram for the same payload.  
**Does not demonstrate:** Physical channel success or inaudibility.  
**Suggested section:** Modulation  
**Suggested caption:** Generated CPFSK spectrum (synthetic payload).  
**Publication status:** Ready

---

## 5. Physical audible calibration

**Filename:** `05-physical-audible-response.png`  
**Path:** `output/article/05-physical-audible-response.png`  
**Provenance:** PHYSICAL_RX  
**Demonstrates:** Measured response of the tested speaker→microphone chain in the audible band.  
**Does not demonstrate:** Universal laptop frequency response.  
**Suggested section:** When Nyquist Meets Real Hardware  
**Suggested caption:** Physical audible-band response estimate for the tested lab path.  
**Publication status:** Ready  
**Source:** `output/samples/calibration_audible.png` / `calibration-audible-physical/`

---

## 6. Physical near-ultrasonic calibration

**Filename:** `06-physical-near-ultrasonic-response.png`  
**Path:** `output/article/06-physical-near-ultrasonic-response.png`  
**Provenance:** PHYSICAL_RX  
**Demonstrates:** Weak / negative detector SNR in the near-US band on this hardware.  
**Does not demonstrate:** Successful near-ultrasonic communication.  
**Suggested section:** When Nyquist Meets Real Hardware  
**Suggested caption:** Near-ultrasonic physical response on the tested hardware (decode not reliable).  
**Publication status:** Ready  
**Source:** `output/samples/calibration_near_us.png`

---

## 7. Physical receiver WAV

**Filename:** `rx.wav`  
**Path:** `output/samples/replay/rx.wav`  
**Provenance:** PHYSICAL_RX  
**Demonstrates:** Real microphone capture of CPFSK HELLO (3500/7500 Hz, 0.12 s) with CRC VALID.  
**Does not demonstrate:** Universal reliability or covert channel practicality.  
**Suggested section:** Live audible results  
**Suggested caption:** Verified physical capture (replay requires `rx.wav.meta.json`).  
**Publication status:** Ready (hash-locked metadata)

---

## 8. Goertzel energy timeline

**Filename:** `07-goertzel-energy-timeline.png`  
**Path:** `output/article/07-goertzel-energy-timeline.png`  
**Provenance:** SIMULATED_RX  
**Demonstrates:** Dual-tone Goertzel energy over symbols in a simulated capture.  
**Does not demonstrate:** Physical room acoustics.  
**Suggested section:** Detection  
**Suggested caption:** Goertzel energy timeline (simulated RX — labelled).  
**Publication status:** Ready

---

## 9. Bit timeline

**Filename:** `08-decoded-bit-timeline.png`  
**Path:** `output/article/08-decoded-bit-timeline.png`  
**Provenance:** SIMULATED_RX  
**Demonstrates:** Hard bit decisions over time after demodulation (simulated).  
**Does not demonstrate:** Physical CRC-valid live decode.  
**Suggested section:** Detection  
**Suggested caption:** Decoded bit timeline (simulated RX).  
**Publication status:** Ready

---

## 10. CRC-valid live-monitor result

**Filename:** `13-live-monitor-crc-valid.png`  
**Path:** `output/article/13-live-monitor-crc-valid.png`  
**Provenance:** MISSING  
**Demonstrates:** (placeholder)  
**Does not demonstrate:** Anything until a real screenshot is added.  
**Suggested section:** Live demo  
**Suggested caption:** Live monitor showing CRC VALID (physical run).  
**Publication status:** MISSING — screenshot required  
**Suggested filename:** `live_monitor_crc_valid.png`

---

## 11. Speed-comparison result

**Filename:** `10-speed-vs-success.png`  
**Path:** `output/article/10-speed-vs-success.png`  
**Provenance:** PHYSICAL_RX  
**Demonstrates:** Trial-count success at several symbol durations (incl. 3/3 @ 70 ms, 2/3 @ 40 ms).  
**Does not demonstrate:** Continuous reliability curves or large-N statistics.  
**Suggested section:** How fast can it go?  
**Suggested caption:** Speed versus CRC-valid frames (small trial counts stated).  
**Publication status:** Ready

---

## 12. FEC experiment

**Filename:** `11-fec-comparison.png`  
**Path:** `output/article/11-fec-comparison.png`  
**Provenance:** PHYSICAL_RX  
**Demonstrates:** Hamming(7,4) campaign 4/4 HELLO vs broader 8/10 none campaign (not like-for-like payload set).  
**Does not demonstrate:** That FEC guarantees correction; CRC remains final.  
**Suggested section:** Forward error correction  
**Suggested caption:** FEC campaign comparison with explicit trial counts.  
**Publication status:** Ready

---

## 13. Failed experiment

**Path:** `experiments/*/trial-*` with `success: false` (local); summaries note CRC failures  
**Provenance:** PHYSICAL_RX  
**Demonstrates:** Non-monotonic / failed trials exist (CRC mismatch, sync failure).  
**Does not demonstrate:** Universal failure modes.  
**Suggested section:** Limitations  
**Suggested caption:** Example CRC-failed physical trial (retain raw WAV locally).  
**Publication status:** Available locally; redact host metadata before publishing dumps

---

## 14. Low-pass mitigation comparison

**Filename:** `12-lowpass-mitigation.png`  
**Path:** `output/article/12-lowpass-mitigation.png`  
**Provenance:** GENERATED_TX  
**Demonstrates:** Note that CPFSK did not reduce audible leakage vs BFSK in the generated near-US comparison.  
**Does not demonstrate:** Physical stealth.  
**Suggested section:** Modulation myths  
**Suggested caption:** Audible-leakage comparison (generated TX).  
**Publication status:** Ready (pointer figure)

---

## 15. Hardware setup photograph

**Filename:** —  
**Path:** —  
**Provenance:** MISSING — photograph required  
**Suggested filename:** `physical-lab-setup.jpg`  
**Demonstrates:** TX/RX placement for the lab demo.  
**Does not demonstrate:** Other rooms/hardware.  
**Suggested section:** Lab setup  
**Suggested caption:** Authorized laboratory speaker–microphone arrangement.  
**Publication status:** MISSING

---

## Additional curated paths

| Path | Provenance |
| --- | --- |
| `output/samples/replay/tx.wav` | GENERATED_TX |
| `output/samples/replay/rx.wav.meta.json` | metadata for PHYSICAL_RX |
| `output/article/04-generated-vs-physical-signal.png` | GENERATED_TX + PHYSICAL_RX |
| `output/article/09-experiment-success-summary.png` | PHYSICAL_RX |
| `configs/conference-audible-demo.yaml` | physically_validated_configuration |
