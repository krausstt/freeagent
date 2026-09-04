# Windows quick start

Everything here works on stock Windows with PowerShell. You do not need WSL,
Git Bash, or a Linux VM.

> **Tested how:** the Python code and its 22 tests are verified. The PowerShell
> scripts are written for Windows PowerShell 5.1 and reviewed for 5.1-only
> syntax, but they were authored on Linux and **have not been executed on a
> Windows machine**. If one misbehaves, say so and it gets fixed — do not
> assume you did it wrong.

## Why the Linux instructions failed you

| Command | Why it failed | Windows equivalent |
|---|---|---|
| `unzip x.zip` | Unix tool, not on Windows | `Expand-Archive x.zip -DestinationPath .` |
| `bash script.sh` | no bash on Windows | `powershell -File script.ps1` |
| `python3` | Windows uses `py` or `python` | `py -3` |
| `a && b` | PowerShell 5.1 has no `&&` | put them on separate lines |

That "Python was not found; run without arguments to install from the
Microsoft Store" message is **not** Python failing — it is a placeholder
Microsoft ships at `...\WindowsApps\python.exe` that exists only to advertise
the Store. The scripts here deliberately skip anything under `WindowsApps`.

## Step 1 — Install Python (once)

```powershell
winget install --id Python.Python.3.12 -e
```

**Then close and reopen PowerShell** so `PATH` refreshes. Check:

```powershell
py -3 --version
```

If you still get the Store advert, switch off the aliases:
*Settings → Apps → Advanced app settings → App execution aliases* → turn off
**python.exe** and **python3.exe**.

## Step 2 — Get the code

```powershell
cd $env:USERPROFILE\dev
git clone https://github.com/krausstt/freeagent.git
cd freeagent
```

No git? Download the ZIP from GitHub and:

```powershell
Expand-Archive freeagent-main.zip -DestinationPath .
cd freeagent-main
```

## Step 3 — Run it

```powershell
powershell -ExecutionPolicy Bypass -File deploy\bootstrap.ps1
```

`-ExecutionPolicy Bypass` applies to that one command only; it does not change
your machine's policy.

The script installs one dependency, **runs the 22 offline tests before touching
ESPN**, checks whether your league needs cookies at all, and only then asks for
them — hidden, via `Read-Host -AsSecureString`.

## Step 4 — Schedule it

```powershell
powershell -ExecutionPolicy Bypass -File deploy\Register-PollTask.ps1
```

Creates a Scheduled Task running every 3 hours as you. It refuses to register
until a manual poll succeeds, so you cannot end up with a task silently failing.

```powershell
Get-ScheduledTask -TaskName 'FreeAgent ESPN Poll' | Get-ScheduledTaskInfo
Start-ScheduledTask -TaskName 'FreeAgent ESPN Poll'
powershell -File deploy\Register-PollTask.ps1 -Unregister
```

A laptop that sleeps will miss runs; `StartWhenAvailable` catches up on wake.
For genuinely unattended polling, a machine that stays on is better — that is
what `deploy/install.sh` and the systemd units are for.

## Running things by hand

```powershell
py -3 tests\test_engine.py
py -3 tests\test_season.py
py -3 tests\test_brief.py

py -3 -m ffdraft.cli verify
py -3 tools\poll_espn.py
py -3 tools\weekly_brief.py
```

Open `dashboard\index.html` in any browser — no server needed.

## Credential storage on Windows

`~/.ffdraft.json` lands at `C:\Users\<you>\.ffdraft.json`.

**`chmod 0600` does nothing useful on Windows** — NTFS uses ACLs, and Python's
`Path.chmod` only toggles the read-only attribute. So the code calls `icacls`
to strip inheritance and grant your account alone, and prints exactly what it
applied. If that fails it says so rather than implying protection it did not
achieve.
