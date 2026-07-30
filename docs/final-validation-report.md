# Final validation report

**Baseline commit:** `478b17a8b9f650bc10f56f2ebe087c50fe039c84`  
**Validation date:** 2026-07-30  
**Environment:** Linux lab host, Python venv, `PYTHONPATH=.`

## 1. Full non-hardware test suite

```bash
PYTHONPATH=. pytest -q -m "not hardware"
```

**Result:** 93 passed, 0 failed, 0 skipped.

## 2. Simulation BFSK

```bash
python -m src.receiver --simulate --message HELLO --modulation bfsk --noise-level 0.01
```

**Result:** `frame success = True`, recovered `HELLO`, BER 0.0.

## 3. Simulation CPFSK

```bash
python -m src.receiver --simulate --message HELLO --modulation cpfsk --noise-level 0.01
```

**Result:** `frame success = True`, recovered `HELLO`, BER 0.0.

## 4. Simulation CPFSK + Hamming(7,4)

```bash
python -m src.receiver --simulate --message HELLO --modulation cpfsk --fec hamming74 --noise-level 0.02
```

**Result:** `frame success = True`, recovered `HELLO`, BER 0.0.

## 5. Provenance validation

Covered by `tests/test_publication_pass.py` (missing meta, corrupt JSON, hash mismatch,
GENERATED_TX / SIMULATED_RX rejection, schema, mandatory fields).

**Result:** all provenance/replay unit tests passed.

## 6. Replay with valid physical capture

```bash
python -m src.replay --input-wav output/samples/replay/rx.wav
```

**Result:** SHA-256 VALID; reconstructed CPFSK 3500/7500 Hz, 120 ms; `frame_success=True`, `HELLO`.

## 7. Replay rejection — missing metadata

```bash
python -m src.replay --input-wav output/samples/demo_tx.wav
```

**Result:** rejected — provenance UNKNOWN / no metadata.

## 8. Replay rejection — modified WAV / hash mismatch

Temporary copy with altered bytes and wrong `wav_sha256`.

**Result:** rejected — SHA-256 mismatch.

## 9. Safety rejection — excessive amplitude

`require_safe(amplitude=0.99, …)` → `SafetyError: amplitude 0.99 outside (0, 0.35]`.

## 10. Safety rejection — excessive duration

`require_safe(… estimated_duration_s=999)` → exceeds 180 s limit.

## 11. Documentation safety scan

```bash
python scripts/docs_safety_scan.py
```

**Result:** OK (no RFC1918 / `/home/<user>` / denylisted host strings in public docs).

## 12. Stage demo simulation mode

```bash
python -m src.stage_demo --simulate --message HELLO --modulation cpfsk
```

**Result:** MODE SIMULATION, CRC VALID, provenance SIMULATED_RX.

## 13. Stage demo verified physical replay

```bash
python -m src.stage_demo --replay output/samples/replay/rx.wav
```

**Result:** PHYSICAL CAPTURE REPLAY, SUCCESS True, recovered HELLO.

## 14. Live audible demo

**Status:** Not executed in unattended validation (requires operator attention / volume).  
Audio devices enumerated: 17 PortAudio devices present.

Recommended command when ready:

```bash
python -m src.live_monitor --remote-tx demo-user@tx-host \
  --remote-output-device 1 --message DEMO_DEMO_334 --modulation cpfsk \
  --symbol-duration 0.07 --frequency-zero 3000 --frequency-one 8000 \
  --repeats 1 --amplitude 0.30
```

## Summary counts

| Metric | Value |
| --- | --- |
| Total tests | 93 |
| Passed | 93 |
| Failed | 0 |
| Skipped hardware | 0 marked (hardware marker reserved) |
| Baseline git commit | `478b17a8b9f650bc10f56f2ebe087c50fe039c84` |
