# Alternative physical channels (lab exploration)

Authorized educational research only. Synthetic payloads only.
No automatic collection of files, credentials, or private data.

This note collects **original / adjacent** ideas beyond laptop-speaker near-US.
Each idea needs PHYSICAL_RX evidence (or an honest negative) before blog claims.

## Priority order

1. Near-US recovery on current speakers ([`near-us-recovery-campaign.md`](near-us-recovery-campaign.md))
2. Hardware swap (mic → external speaker/DAC → other laptop)
3. PC motherboard beeper / piezo
4. Infrasound probe (likely negative on laptop transducers)
5. Sister modalities (optical LED/brightness) as separate PoCs

## Channel catalogue

### A. Different microphone (same TX)

**Why:** MEMS laptop mics often roll off HF; a USB condenser may extend usable band.  
**Test:** Recalibrate 12–21 kHz; rerun NU-A/B.  
**Success:** CRC-valid near-US frame with stated N.

### B. External speaker / USB DAC (same mic)

**Why:** Laptop speakers are the usual HF bottleneck.  
**Test:** New audible + near-US calib; do not reuse old SNR curves.

### C. PC beeper / motherboard speaker

**Why:** Distinct from the “main” DAC path — historically present on desktops; rare/disconnected on many modern laptops.  
**Probe:**

```bash
# Existence / permission checks vary by OS. Examples (Linux):
ls -l /dev/input/by-path/*spkr* 2>/dev/null
# Console bell (may be redirected to sound server — not true PC speaker):
printf '\a'
```

If a true PC speaker exists, first experiments are:

1. Single calibrated beep / tone burst
2. Extremely slow BFSK (long symbols) with a synthetic `HI` payload
3. Mic capture + Goertzel on the observed peak (often low audible kHz, not US)

**Honest expectation:** audible, narrowband, slow — still a valid “hidden path” story if the DAC speakers are monitored but the beeper is forgotten.

### D. Piezo / buzzer

**Why:** Better high-frequency mechanical response than laptop cones.  
**Test:** USB sound dongle driving a piezo, or SBC GPIO buzzer, same RX mic stack.

### E. Infrasound (IS) instead of ultrasound (US)

**Why people ask:** mirror of near-US — “go below hearing instead of above”.  
**Why it usually fails on laptops:** high-pass filters, tiny speakers, HVAC noise, need for very long symbols.  
**Test (only if curious):** calib sweep **20–200 Hz** with long dwell; report detector SNR. Expect weak/negative; publish the negative.

### F. Optical sister channel (out of acoustic scope)

Screen brightness or LED modulation with a photodiode/camera. Mention as air-gap sibling; implement only as a separate module if pursued.

## Safety

- Same amplitude / duration / opt-in policies for any DAC playback
- Do not drive piezo/beeper at damaging duty cycles
- Never claim stealth / inaudibility without measurements
- Label every artefact with provenance

## Results log

| Date | Channel | Hardware | Result | Provenance |
| --- | --- | --- | --- | --- |
| _(pending)_ | | | | |
