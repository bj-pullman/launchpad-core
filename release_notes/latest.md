# Launchpad Update Notes

## Media Catalog Checkout Extensions

- Added Extend Due Date for active and overdue Student Checkouts and Dashboard Needs Attention entries.
- Choose a later Return By date without returning or recreating the checkout.
- Extensions preserve cart ownership restrictions and record the previous date, new date, and actor in the audit log.
- Checkout and overdue counts refresh after saving. No schema change is required.

## Ledger Import Review Improvements

- Compact Ledger-style review table with server-side filtering and 10/25/50/100-row pagination.
- All active department Finance Records appear when opening the selector; search narrows the full list without loading additional pages.
- Review actions update the table and counts in place, preserving filters and the current page when possible.
- Concurrent changes are detected before saving a stale review action.
- Future imports preserve original results and transaction membership in the existing import-run notes field.
- Original import results are separate from current unresolved counts; unavailable legacy figures are explicitly labeled.
- Review Unlinked Transactions appears beside Import Ledger with the unresolved count.
- Both Ledger tables use seven readable columns, normalized dates, and visible Link Record / Create Record actions with Finance-style dialogs.
- Review and Import actions are right-aligned; Back to Ledger uses the existing chevron button style below the navigation.
- Imports reconcile earlier payments after later original encumbrances create their Records, eliminating source-order-dependent missed links.
- No database schema or configuration change is required.

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
