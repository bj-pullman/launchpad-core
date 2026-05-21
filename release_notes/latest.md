# Launchpad Update Notes

## System Maintenance Update

> Adds safer update handling, manual backup support, and a more user-friendly update screen.

---

## What's New

- Added System Maintenance under Settings.
- Added manual backup generation.
- Added backup history tracking.
- Added update checking with friendly version labels.
- Added release-note support for future updates.
- Improved protection for hosting/config files.

---

## What To Expect

| Item | Behavior |
|---|---|
| Backup | A backup is generated automatically before updates |
| Restart | The Launchpad service may restart |
| `.env` | Protected |
| `web.config` | Protected |
| Service files | Protected |
| Database files | Included in backups |

---

## Recommended Actions

- Review these notes before applying the update.
- Apply updates during a low-usage window.
- Confirm the backup completes successfully.

---

<details>
<summary>Advanced Technical Details</summary>

Protected files include:

```text
.env
web.config
wsgi.py
modules/core/app_factory.py
service/*.xml
service/*.exe
service/*.config
service/*.ps1
service/*.bat
service/*.cmd