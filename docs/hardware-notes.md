# Hardware notes

Redacted device descriptions only in publishable metadata (no usernames, home paths, serials).

## Observed setups (this lab)

### Capture host (Cursor laptop)

- ALC897 Analog / Rear Mic capture path historically reliable
- Prefer analog output device over HDMI sinks for TX when same-host
- Same-process duplex ALSA often unreliable → two-process RX-then-TX

### Remote TX (`t11` / 192.168.68.109)

- ThinkPad with sof-hda-dsp speakers; sounddevice device index **1** worked for playback
- Pulse/PipeWire Speaker sink should be unmuted (~80–85%)
- Capture remains on the local host microphone

## Hardware limits

- Nyquist (Fs/2) is not the physical response limit
- Near-ultrasonic (≳17 kHz) often rolls off; only use carriers with measured `estimated_detector_snr_db`
- Do not claim inaudibility without measurements
