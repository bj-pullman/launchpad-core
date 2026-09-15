# Staff Absence Google Apps Script

This public intake project and the sibling `staff-absence-review-form` project supply two isolated web apps backed by one private Google Sheet:

- **Public intake:** anonymous, mobile-first, and append-only. It accepts only the absence fields in `Index.html`.
- **Manager review:** Google sign-in required, domain-restricted, and exact-email authorized. It can load and decide only the UUID in the review URL.

Launchpad remains private and authoritative. Google never calls Launchpad. Launchpad polls the Sheet outbound, resolves the employee and current department from the submitted district email, applies decisions through the existing Staff Status request services, and sends all email.

## Security boundary

The public form cannot list or query requests, users, departments, settings, approvals, Launchpad URLs, credentials, or APIs. Review functions derive identity only from `Session.getActiveUser().getEmail()`, fail closed when blank, and reauthorize every read and write. Normal reviewers must match the row's `approval_manager_email`; global reviewers may review any row. GET only renders a page and never mutates state.

The Sheet is a private queue/handoff layer, not a source of truth. If a final Google value disagrees with Launchpad, Launchpad repairs the row. Do not share the Sheet publicly.

## Files

- `Code.gs` — intake, safe Sheet initialization, authenticated review services, locking, and validation
- `Index.html` — public mobile intake
- `appsscript.json` — anonymous intake deployment manifest
- `../staff-absence-review-form/` — separate domain-authenticated review project
- `SETUP.md` — deployment, migration, and test runbook

## Queue schema

The first 18 existing columns remain unchanged. The editor-only `initializeAbsenceRequestSheet_` function appends eleven review/workflow columns if missing and preserves every existing row and header position. Its trailing underscore prevents browser clients from invoking it.

```text
submission_uuid, submitted_at, staff_email, absence_type, duration_mode,
start_date, end_date, start_time, days_value, notes,
processing_status, processing_started_at, processed_at, launchpad_request_id,
processing_error, processing_attempts, last_processing_attempt_at, processing_claim_id,
staff_display_name, department_name, approval_manager_email, workflow_status, reviewed_by, reviewed_at, decision_note,
launchpad_sync_status, launchpad_synced_at, launchpad_sync_error, decision_claim_id
```

New submissions start with `processing_status=pending`, `workflow_status=pending`, and `launchpad_sync_status=pending`. Launchpad claims imports with `processing_claim_id` and decisions with `decision_claim_id`. The SQLite UUID uniqueness constraint is authoritative for import idempotency. Final request and email state is persisted in Launchpad.

Result-email state prevents ordinary poll retries from sending duplicates. SMTP has an unavoidable narrow ambiguity: a provider may accept a message and then disconnect before Launchpad receives confirmation. No SMTP-only implementation can prove non-delivery in that edge case.

See [SETUP.md](SETUP.md) before publishing either deployment.
