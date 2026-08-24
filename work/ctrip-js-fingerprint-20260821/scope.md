# Case Scope

## meta
- case_id: ctrip-js-fingerprint-20260821
- created: 2026-08-21T16:41:33.2683718+08:00
- operator: local
- primary_skill: js-reverse/SKILL.md
- primary_id: R3
- lead_role: lead
- specialist_roles: [cre]
- hint: 携程网页 JavaScript 设备指纹与账号关联风险静态分析

## auth
- status: granted
- basis: own_system
- evidence_of_auth: user-provided local capture for defensive analysis
- MUST NOT proceed if status != granted

## in_scope
- assets:
  - D:\workspace\vscode\jpz-reverse\05ctrip-js-reverse
- surfaces: [web, javascript, device_fingerprinting]
- activities: [offline_static_reverse, evidence_analysis, report]

## out_of_scope
- assets: []
- activities: [dos, phishing_real_users, unrestricted_exfil]

## network_profile
- mode: offline
- notes: |
    offline | lab_only | authorized_target_only | unrestricted_lab
    Change mode only after auth.status = granted.

## deliverables
- report: true
- field_journal: true
- diagrams: true
- timeline: true

## constraints
- timebox: {}
- stealth: low
- data_handling: anonymize

## signoff
- ready_for_act: true
- checklist:
  - [x] auth.status = granted
  - [x] in_scope.assets non-empty OR offline sample path set
  - [x] network_profile.mode chosen
  - [x] out_of_scope reviewed
  - [x] roles assigned (see skills/ops/role-map.md)

## ops_refs
- skills/ops/scope-contract.md
- skills/ops/evidence-finding-path.md
- skills/ops/role-map.md
- skills/ops/timeline-workitem.md
- skills/ops/IDENTITY.md
