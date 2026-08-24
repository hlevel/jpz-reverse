# Timeline (append-only)

## 2026-08-21T16:41:33.2683718+08:00 | lead | init
- action: case-init
- command_or_ref: skills/scripts/case-init.ps1
- result_summary: case directory created; scope subsequently corrected for authorized offline static analysis
- artifacts: [scope.md, workitems.md]
- evidence_ids: []
- next: route to js-reverse and begin static triage

## 2026-08-21T17:00:00+08:00 | lead/cre | static triage
- action: hash deduplication and keyword triage
- command_or_ref: rg / Get-FileHash / local JS samples
- result_summary: located c-sec, Chloro device collection, WebCore bot detection, and persistent identifiers
- artifacts: [evidence/E-001.md, evidence/E-002.md, evidence/E-003.md, evidence/E-004.md]
- evidence_ids: [E-001, E-002, E-003, E-004]
- next: synthesize findings and report

## 2026-08-21T17:20:00+08:00 | doc | report
- action: Evidence -> Finding -> Path synthesis
- command_or_ref: docs-generator
- result_summary: report completed; Canvas-only hypothesis rejected in favor of multi-factor device/network/behavior linkage
- artifacts: [report/2026-08-21_js-reverse-ctrip-device-linkage-report.md]
- evidence_ids: [E-001, E-002, E-003, E-004]
- next: optional comparison against 60 browser-profile exports

## 2026-08-21T18:00:00+08:00 | cre/doc | profile correlation
- action: compare 25 VirtualBrowser fingerprint exports
- command_or_ref: ConvertFrom-Json / Group-Object / SHA256
- result_summary: unique Canvas and device cookies, but 10 duplicated proxy endpoint pairs covering 20 profiles; shared `_udl` across 23 profiles
- artifacts: [evidence/E-005.md, report/2026-08-21_js-reverse-ctrip-device-linkage-report.md]
- evidence_ids: [E-005]
- next: obtain remaining profiles or analyze `_udl` semantics and behavior logs
