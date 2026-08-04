# Near-US payload campaign (2026-08-04)

Config: CPFSK **15000/16000 Hz**, Tsym=**0.25 s**, FEC=**hamming74**, repeats=**2**, amp=**0.30**, freq_search=**±150 Hz**, bandpass=off, min_ratio=1.08  
TX: remote lab host via `ACOUSTIC_REMOTE_TX`  
Provenance: **PHYSICAL_RX**

## RX improvements used

- Carrier neighbourhood search (±150 Hz, step 25 Hz) on decode + live bars
- Softer min_ratio (1.08) for near-US
- Longer capture tail (6 s)
- Mild symbol-duration search (±3 %)
- Bandpass off by default (was flipping CRC bits on audible trials)
- SSH remote `--message` now `shlex.quote`d (fixes `$` / `!` shell expansion)

## Results

| Payload | CRC | Recovered | Exact match | Notes |
| --- | --- | --- | --- | --- |
| `p4$$w0rd` (1st) | CRC VALID | `p41068552w0rd` | No | SSH expanded `$$` → PID; acoustic CRC was for the wrong TX string |
| `user@domain.tld` | CRC VALID | `user@domain.tld` | Yes | |
| `demo_sinclair_2000` | CRC VALID | `demo_sinclair_2000` | Yes | |
| `this_is_working!!!` | CRC VALID | `this_is_working!!!` | Yes | |
| `p4$$w0rd` (retry after quote fix) | CRC VALID | `p4$$w0rd` | Yes | |

**Score (exact payload match):** 4/4 intended strings after quoting fix (plus one corrupted-by-SSH trial that still CRC-validated the wrong string).

WAVs under `output/lab_nearus_payloads/`.
