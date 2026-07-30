# Final publication audit

## Baseline (before this pass)

* **Git commit:** `478b17a8b9f650bc10f56f2ebe087c50fe039c84`
* **Tests at baseline (prior session):** 60 passed
* **Branch:** `main`

## Test results (after this pass)

* **Command:** `PYTHONPATH=. pytest -q -m "not hardware"`
* **Result:** **93 passed**, 0 failed, 0 skipped (no hardware-marked tests in suite yet)
* **Docs safety scan:** OK (`python scripts/docs_safety_scan.py`)

## Current architecture

Synthetic CLI payload → protocol framing (CRC-16) → optional Hamming(7,4) on body →
BFSK or CPFSK modulation → speaker / WAV → air → microphone → bandpass →
exact-frequency Goertzel → bounded symbol-duration + sample-phase search →
soft energy preamble correlation (legacy hard Hamming matcher retained) →
optional soft log-energy frame combining → CRC decision → recovered text.

Shared production decode path: `src.receiver.decode_from_samples` (used by
receiver, live_monitor, experiment, replay, stage_demo).

## Current physical evidence

* Audible remote TX → local RX: **8/10** CRC-valid (CPFSK, 3500/7500 Hz, 0.12 s).
* Hamming(7,4) HELLO: **4/4** CRC-valid (small N).
* Fast audible `DEMO_DEMO_334`: **3/3** at 70 ms (3000/8000); **2/3** at 40 ms.
* Near-US physical calibration: weak/negative detector SNR — **decode not reliable**.
* Curated verified capture: `output/samples/replay/rx.wav` (+ `.meta.json`, SHA-256 locked).

## Current simulated / generated evidence

* `output/samples/{reliable,fast,turbo,demo,near_us}_*` — GENERATED_TX / SIMULATED_RX.
* Benchmark / modulation-comparison trees — SIMULATED_RX / GENERATED_TX.
* Article figures under `output/article/` labelled by provenance.

## Documentation inconsistencies found (and corrected)

* Samples README claimed no live captures while physical captures existed.
* Absolute “no network component” ignored optional SSH playback orchestration.
* “120 ms practical ceiling” / “100% success” wording without trial context.
* Incomplete project layout vs current modules.
* Private IPs/hostnames (`192.168.*`, lab user@host) in public docs/scripts.
* Soft sync / majority vote named more “soft” than implemented (hard match / hard vote).

## Safety inconsistencies found (and corrected)

* Transmitter / live_monitor / calibration playback not consistently gated.
* Centralized `assert_playback_allowed` / `assert_calibration_playback` now required on public playback paths.

## Provenance inconsistencies found (and corrected)

* Replay assumed PHYSICAL_RX when metadata missing.
* Incomplete replay metadata (no schema / hash).
* Stage replay used default decoder config instead of verified metadata.

## Changes implemented during this pass

* Fail-closed provenance schema + SHA-256 replay (`src/provenance.py`, `src/replay.py`).
* Soft energy correlation sync + soft log-energy combining + bounded clock-drift search.
* Exact-frequency Goertzel (already partially present; documented/tested).
* CPFSK actually used in receiver `--simulate`.
* Stage wizard real multi-mode flow; production decode pipeline.
* `configs/conference-audible-demo.yaml`.
* Docs scrub, samples catalogue, campaign docs, evidence manifest, article figures.
* GitHub Actions CI + docs safety scan.
* Expanded publication tests (`tests/test_publication_pass.py`).

## Remaining limitations

* Live-monitor CRC-valid screenshot still **MISSING** for the article.
* Hardware setup photograph still **MISSING**.
* Small trial counts — do not publish as universal reliability.
* Local `experiments/` dumps may still contain lab host metadata (not scanned for publication; use redacted `output/samples/experiment-summaries/`).
* Same-host live demo not executed in this pass (devices present; requires operator).
* Non-monotonic symbol-duration results remain environment-dependent.
