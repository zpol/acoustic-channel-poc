# When Nyquist Meets Real Hardware: Why the Near-Ultrasonic Channel Failed

**Blog draft — Part 2**  
Companion to [Part 1](https://medium.com/@keyboardsamurai007/no-network-required-building-an-acoustic-data-channel-with-python-for-data-exfil-part-1-02c3798a033c)  
Repository: https://github.com/zpol/acoustic-channel-poc/  
Draft git baseline: `ce57441` (update on publish)

---

## Beyond the air gap — Part 2

In Part 1 we showed that a short synthetic payload can leave one laptop, cross a room as sound, and arrive on another microphone with a valid CRC.

That channel was **audible**.

The natural follow-up question is the one every demo audience asks:

> Can you do the same thing above human hearing?

At a sample rate of 48 kHz, the mathematical Nyquist frequency is 24 kHz. On paper, carriers at 18, 19, or even 20 kHz look comfortable.

Our physical tests showed why that paper comfort is misleading.

This part is about the gap between **digital possibility** and **transducer reality**.

---

## A deliberately limited question

We did not ask whether ultrasound can exist in nature, or whether laboratory ultrasonic transducers can carry data.

We asked something narrower:

```
On ordinary laptop speakers and a consumer microphone path,
with the same educational Python stack from Part 1,
can we recover a CRC-valid frame using near-ultrasonic carriers?
```

Payloads remained synthetic and manually entered (`HELLO`, `DEMO-LAB-2027`, …).

Near-ultrasonic mode required an explicit opt-in flag. The software does not raise the operating-system volume by itself.

Evidence stayed labelled:

```
GENERATED_TX      digitally synthesized transmitter waveform
SIMULATED_RX      software channel impairment
PHYSICAL_RX       real microphone capture
PHYSICAL_REPLAY   verified replay of a physical capture
```

---

## The Nyquist illusion

Digital sampling theory says:

```
Fs = 48 000 Hz
Nyquist = Fs / 2 = 24 000 Hz
```

So a 19.5 kHz sine wave can be represented by discrete samples without aliasing.

That statement is about **representation**.

It is not a statement about:

- the laptop speaker cone
- the amplifier bandwidth
- the codec reconstruction filter
- the microphone capsule
- the input anti-alias filter
- Windows/macOS/Linux audio processing
- Automatic Gain Control
- noise suppression
- echo cancellation

A sample rate buys you a Nyquist limit.

It does not buy you a flat physical response up to that limit.

---

## What “near-ultrasonic” meant here

In this project, near-ultrasonic means carriers in the upper audio / lower ultrasonic edge that a **48 kHz consumer audio path** might still attempt to play — roughly **15–21 kHz** in the physical sweep, and classic demo pairs such as **18.5 / 19.5 kHz** in generated examples.

That is not the same as a dedicated ultrasonic modem at 40 kHz with matched transducers.

It is the question people actually ask when they look at a laptop:

> If the DAC can sample it, can the speaker send it?

---

## What the generator “proves”

Digitally, generation is easy.

We can synthesize a CPFSK frame with near-ultrasonic carriers, save a WAV, and plot a clean spectrogram.

That artefact is **GENERATED_TX**.

It proves:

- the modulator can place energy at those frequencies in floating-point samples
- the file format can store them
- a spectrogram of the file looks intentional

It does **not** prove:

- the speaker radiates those frequencies at useful amplitude
- the microphone recovers them above the noise floor
- a CRC-valid frame will survive the room

Part 1 already warned about this trap. Near-ultrasonic makes the trap more tempting, because the digital plot looks “secret” even when the physical path is dead.

Repository examples:

```
output/samples/near_us_HELLO_tx.wav
output/samples/near_us_HELLO_spectrogram.png
```

Provenance: **GENERATED_TX**.

---

## Physical calibration: audible vs near-US

We ran frequency sweeps on the same laboratory TX→RX path used for the audible campaigns.

### Audible band (2–10 kHz) — PHYSICAL_RX

Path: `output/samples/calibration-audible-physical/`

Highlights from the measured detector SNR curve:

- Energy was usable in parts of the mid band
- Calibration recommended pairs around **2000 / 3750 Hz** with **positive** estimated detector SNR (≈ +4.6 dB on the best ranked pair)
- Live demos later used **3500 / 7500 Hz** successfully (Part 1 campaigns)

Positive detector SNR does not mean “loud in dB SPL”. It means the Goertzel detector saw more energy on the probe tone than on the estimated noise reference for that setup.

### Near-ultrasonic band (15–21 kHz) — PHYSICAL_RX

Path: `output/samples/calibration-near-us-physical/`

Highlights:

```
MOST_RELIABLE:     15750 / 18000 Hz   ≈  -4.1 dB detector SNR
BEST_COMPROMISE:   15000 / 16000 Hz   ≈  -6.5 dB detector SNR
HIGHEST_FREQUENCY: 19750 / 20750 Hz   ≈ -38.7 dB detector SNR
```

Across the sweep, absolute estimated detector SNRs were **low or negative**.

The honest status recorded in metadata:

```
near_us_status: weak_or_unusable
```

Figure (PHYSICAL_RX):

```
output/article/14-audible-vs-near-us-calibration.png
```

Caption suggestion:

> Physical frequency-response estimates for the tested laptop speaker → microphone path. Audible-band probes can show positive detector SNR; the 15–21 kHz sweep stays weak or negative. Not a universal laptop curve.

---

## Why the chain fails before Nyquist

Think of the path as a product of filters you did not design:

```
Software samples
  → OS mixer / resampling
  → output codec + reconstruction filter
  → amplifier
  → tiny loudspeaker
  → air + room
  → microphone capsule
  → input filter / codec
  → AGC / NS / AEC (sometimes)
  → receiver Goertzel windows
```

Near 20 kHz, several of those stages often roll off hard on consumer devices.

Typical failure modes we observed or must assume on this class of hardware:

1. **Speaker roll-off** — laptop drivers are not ultrasonic transducers.
2. **Microphone roll-off** — many MEMS mics are specified for speech, not 20 kHz telemetry.
3. **Processing** — echo cancellation and noise suppression may treat steady tones as nuisance.
4. **Low radiated energy** — even if a tone exists, it may sit under room noise at the detector.
5. **Ambiguous “best” carriers** — ranking frequencies by residual energy can still yield **negative** SNR. “Best of a bad set” is still bad.

Nyquist tells you the digital ceiling.

The speaker and microphone tell you the usable ceiling.

On this tested pair, the usable ceiling for a robust data channel was in the **audible** region — not the near-ultrasonic edge.

---

## Audible leakage and the myth of automatic stealth

Even when the intended carriers sit high, nonlinearities and abrupt transitions can create energy at lower frequencies.

We compared generated BFSK and CPFSK near-US waveforms in software. CPFSK did **not** automatically show lower audible-band leakage than BFSK in that digital comparison.

Figure / note:

```
output/article/12-lowpass-mitigation.png
```

Provenance: **GENERATED_TX** (comparison note).

So even before physics kills the high carriers, “ultrasonic” is not a synonym for “inaudible” or “undetectable”.

Defenders should not assume attackers need perfect ultrasonic transducers. Attackers may simply use **audible** acoustic channels, as Part 1 demonstrated.

---

## What about infrasound instead of ultrasound?

A frequent mirror idea is:

> If high frequencies fail, try very low ones — infrasound (IS), below ~20 Hz.

Digitally, 48 kHz sampling can represent a 10 Hz tone easily.

Physically, laptop speakers and microphones are often **worse** at infrasound than at near-ultrasound:

- small speakers are poor subwoofer substitutes
- input paths frequently high-pass away rumble
- at 10 Hz you need **long** symbols to contain multiple cycles (slow throughput)
- HVAC and building vibration dominate the noise floor

So infrasound is an interesting research question for specialized sensors — not a free upgrade path for the same laptop PoC.

We keep it on the list of **alternative physical channels** to probe later (with honest negative results if the hardware cannot radiate or capture it). It is not a shortcut around the near-US failure.

---

## Defensive takeaways

An acoustic channel remains a niche, slow, fragile path.

Near-ultrasonic ambitions do not change that. On consumer audio hardware they often make it **more** fragile.

Practical defensive ideas from this work:

- Disable or restrict audio playback/capture on hosts that must stay air-gapped
- Treat persistent narrowband tones with regular symbol timing as suspicious — whether audible or not
- Where high frequencies are unnecessary, low-pass filtering can reduce ultrasonic-adjacent leakage
- Do not equate “48 kHz device” with “usable 20 kHz covert modem”
- Remember the quieter threat: an **audible** structured channel that simply works

Detection heuristics remain signal analysis, not malware signatures:

```
stable narrow peaks
alternation between two carrier regions
repeated symbol durations
long structured tone sequences
```

---

## What Part 1 already proved (for contrast)

On the same laboratory storyline, audible CPFSK recovered CRC-valid frames, including:

```
Remote TX → local RX @ 120 ms, 3500/7500 Hz:  8/10
Hamming(7,4) HELLO:                           4/4
Fast DEMO_DEMO_334 @ 70 ms, 3000/8000 Hz:     3/3
```

Those counts are small. They are still **physical successes** with provenance.

Near-ultrasonic calibration on the same class of path did not produce a comparable success story.

That contrast is the point of Part 2.

---

## Reproducible evidence in the repository

Near-US physical calibration package:

```
output/samples/calibration-near-us-physical/
  measurements.csv
  metadata.json
  response.png
  report.md
```

Audible physical calibration package:

```
output/samples/calibration-audible-physical/
```

Article figures:

```
output/article/05-physical-audible-response.png
output/article/06-physical-near-ultrasonic-response.png
output/article/14-audible-vs-near-us-calibration.png
```

Verified audible physical replay (from Part 1):

```
python -m src.replay --input-wav output/samples/replay/rx.wav
```

---

## What we will try next

Part 2 stops at an honest negative for near-US on the **tested** speaker/microphone combination.

We are not done experimenting.

Next work (documented in the repo, for a later article if results justify it):

1. **Near-US recovery campaign** — use the *least bad* calibrated carriers (e.g. 15/16 kHz), much longer symbols, FEC, repeats, and search — before claiming the band is impossible on this host.
2. **Hardware swaps** — different microphone, external DAC/speaker, another laptop — each as a separate campaign.
3. **Alternative transducers** — PC motherboard beeper (if present), piezo/buzzer, and carefully scoped sister ideas (including infrasound probes where the hardware allows measurement).

Success will still mean:

```
CRC VALID
```

with an explicit trial count and a provenance label.

Failure will still be published as failure.

---

## Closing

Nyquist is a property of sampling.

Speakers and microphones are properties of the physical world.

Between them sits the entire audio stack — and that is where near-ultrasonic laptop channels often die.

The interesting lesson is not that ultrasound is impossible.

It is that **a clean digital waveform at 19 kHz is not evidence**.

The room, the cone, and the capsule get a vote.

On our tested hardware, they voted no.

---

## Operator checklist before Medium publish

Still missing for richer illustration (do not fabricate):

- [ ] Live-monitor screenshot with CRC VALID (PHYSICAL_RX) — suggested: `output/screenshots/live_monitor_crc_valid.png`
- [ ] Lab setup photograph — suggested: `output/screenshots/physical-lab-setup.jpg`
- [ ] Optional: one failed near-US live attempt log + spectrogram labelled PHYSICAL_RX

Suggested capture commands (authorized lab only):

```bash
# Audible success screenshot candidate
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message DEMO_DEMO_334 --modulation cpfsk \
  --symbol-duration 0.07 --frequency-zero 3000 --frequency-one 8000 \
  --repeats 1 --amplitude 0.30

# Near-US recovery probe (experimental; expect possible failure)
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message HELLO --modulation cpfsk \
  --near-ultrasonic --fec hamming74 \
  --frequency-zero 15000 --frequency-one 16000 \
  --symbol-duration 0.25 --repeats 2 --amplitude 0.30
```

See also:

- `docs/near-us-recovery-campaign.md`
- `docs/alternative-physical-channels.md`
- `configs/near-us-recovery.yaml`
