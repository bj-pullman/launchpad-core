# Staff Absence Google Apps Script

This single Apps Script project supplies two web-app deployments backed by one private Google Sheet:

- **Public intake:** anonymous, mobile-first employee submission.
- **Manager review:** Google sign-in required, available to any signed-in Google account, mobile-first, and exact-email authorized.

Launchpad remains private and authoritative. Google never calls Launchpad. Launchpad polls the Sheet outbound, resolves each employee and current department from the submitted district email, applies decisions through the existing Staff Status services, and sends all email.

## Project files

- `Code.gs` — routing, intake, safe Sheet initialization, authenticated review services, locking, and validation
- `Index.html` — public mobile intake
- `Review.html` — authenticated mobile approval and denial experience
- `AccessDenied.html` — fail-closed response for missing or unauthorized identity
- `appsscript.json` — shared manifest for both deployments
- `SETUP.md` — deployment, migration, and test runbook

## Routing

`doGet(e)` renders `Index.html` by default. It selects the review page only for:

```text
REVIEW_DEPLOYMENT_URL?action=review&id=<submission_uuid>
```

GET never makes a decision and uses a read-only queue accessor. Approval and denial call `submitReviewDecision`, which takes only UUID, decision, and note. It locks, rereads, obtains the active Google identity server-side, reauthorizes, verifies pending state, and only then writes the decision.

## Security boundary

The public UI contains no review link, reviewer configuration, employee directory, department list, Launchpad URL, credentials, or query interface. Anonymous users cannot load protected request details, list requests, approve, deny, or alter existing rows.

Every review read and write independently requires a nonblank `Session.getActiveUser().getEmail()`. The normalized address must be exactly listed in `APPROVER_EMAILS` or `GLOBAL_APPROVER_EMAILS`. A normal approver must also match the row's `approval_manager_email`; a global approver may review any request. There is no domain restriction in this authorization logic: explicitly configured Gmail or other Google accounts are supported. Missing identity fails closed. Reviewer identity is never accepted from browser input.

The Sheet is a private queue/handoff layer, not a source of truth. Launchpad repairs conflicting Google state when its local request is already final. Never share the Sheet publicly.

## Script Properties

Configure these once in the shared project:

- `ABSENCE_SUBMISSION_SHEET_ID` — private queue spreadsheet ID
- `APPROVER_EMAILS` — comma-separated exact assigned-manager addresses
- `GLOBAL_APPROVER_EMAILS` — comma-separated exact global-reviewer addresses; may be blank

Whitespace and case are normalized, but authorization remains exact-address matching.

For example, the assigned district manager and a personal global reviewer can be configured as:

```text
APPROVER_EMAILS=bjpullman@sheridanschools.org
GLOBAL_APPROVER_EMAILS=personal.account@gmail.com
```

Configure that same personal address in Launchpad's **Global Reviewer Emails** setting. Launchpad independently rejects a Google decision unless `reviewed_by` is the request's exact manager or one of its configured global reviewers.

## Queue schema

The first 18 existing columns remain unchanged. The editor-only `initializeAbsenceRequestSheet_` function appends missing review/workflow columns without changing existing rows or header order. Its trailing underscore prevents browser invocation.

```text
submission_uuid, submitted_at, staff_email, absence_type, duration_mode,
start_date, end_date, start_time, days_value, notes,
processing_status, processing_started_at, processed_at, launchpad_request_id,
processing_error, processing_attempts, last_processing_attempt_at, processing_claim_id,
staff_display_name, department_name, approval_manager_email, workflow_status,
reviewed_by, reviewed_at, decision_note, launchpad_sync_status,
launchpad_synced_at, launchpad_sync_error, decision_claim_id
```

New submissions start as pending. Launchpad claims imports and decisions with UUID-based claim fields. The SQLite `submission_uuid` uniqueness constraint remains authoritative. Final request and result-notification state is persisted in Launchpad.

Result-email state prevents ordinary polling duplicates. SMTP retains the narrow unavoidable ambiguity where a provider may accept a message and disconnect before returning confirmation.

## Google identity limitation

Google documents that `Session.getActiveUser().getEmail()` can return a blank value for web apps deployed to **execute as the deploying user**, especially when the visitor is outside the deployer's Workspace domain. This project deliberately fails closed when that happens. Therefore, a personal Gmail address can be configured as a global reviewer, but it must be tested against the production reviewer deployment before relying on it. If Google withholds the address, the reviewer sees **Sign-in Required** and cannot read or decide the request. No weaker identity fallback or browser-supplied email is used.

See Google's [Session identity documentation](https://developers.google.com/apps-script/reference/base/session) and [web-app permissions documentation](https://developers.google.com/apps-script/guides/web).

See [SETUP.md](SETUP.md) before publishing either deployment.
