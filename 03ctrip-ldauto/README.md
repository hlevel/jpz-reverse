# 03ctrip-ldauto

Python automation runner for operating the Ctrip app through LDPlayer.

`work/` is a temporary reference area. The formal v1 code lives in
`src/ctrip_ldauto/`.

## V1 scope

V1 provides the runnable project backbone:

- YAML config loading for `system`, `ld`, and `xc` modules.
- Console + file logging under `data/logs/`.
- LDPlayer lifecycle wrapper around `ldconsole.exe`.
- ADB wrapper for app launch, package checks, tap/swipe/input/back/screenshot.
- Task API client and local task state files.
- One worker thread per emulator.
- Replaceable business module boundary.
- Initial Ctrip + PCAPdroid business flow placeholders.

The concrete Ctrip page coordinates/templates are intentionally left for the
next module implementation.

## Setup

```powershell
cd 03ctrip-ldauto
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Config

Copy the example and edit local values:

```powershell
Copy-Item configs\config.example.yaml configs\config.yaml
```

Important sections:

- `system`: runtime behavior, exit wait, log level, data directory.
- `ld`: LDPlayer paths, multiplayer path, emulator instances, and diagnostics.
- `xc.app`: Ctrip and PCAPdroid package names.
- `xc.task`: task website API settings.
- `xc.rule`: per-instance rest/browse/retry strategy.

## Run

Validate config:

```powershell
python -m ctrip_ldauto --check-config
```

Run automation:

```powershell
python -m ctrip_ldauto --config configs\config.yaml
```

Validate configured LDPlayer instances without starting them:

```powershell
python -m ctrip_ldauto --check-ld --no-start-ld
```

Run a real LDPlayer diagnostic that may start configured instances and then
close the instances started by the diagnostic:

```powershell
python -m ctrip_ldauto --check-ld --ld-running-wait-seconds 20 --ld-adb-wait-seconds 15
```

When running from source without installing the package, set `PYTHONPATH` to
`src` or use editable install:

```powershell
python -m pip install -e .
python -m ctrip_ldauto --check-config
```

## Test

Run the offline LDPlayer core tests. These tests mock `ldconsole.exe` and ADB,
so they do not start a real emulator.

```powershell
python -m unittest discover -s tests -v
```

## Design doc

See [docs/design.md](docs/design.md).
