# Staff Absence Public Form

This directory contains the public, mobile-first Google Apps Script intake application for Staff Status absence requests.

**The public form has no direct access to Launchpad.**

**Launchpad initiates all communication with Google.**

## Why this architecture exists

Launchpad is hosted only on the district network and must remain private. The Apps Script application therefore writes new submissions to a private Google Sheet. Launchpad periodically connects outbound to the Google Sheets API, validates queued submissions using its own identity and Staff Status data, and creates the normal pending absence request.

```text
PUBLIC INTERNET

Employee phone
      |
      v
Google Apps Script web app
      |
      v
Private Google Sheet queue
      ^
      |
      | Google Sheets API (outbound from Launchpad)
      |
Private Launchpad server

PRIVATE DISTRICT NETWORK
```

There is no Apps Script-to-Launchpad request, webhook, public Launchpad API, tunnel, or browser-to-Launchpad call.

## Component roles

- **Apps Script:** Validates a single untrusted submission and appends it to the queue. It cannot list, search, retrieve, edit, approve, reject, or delete requests.
- **Google Sheet:** A private handoff queue containing submitted intake fields and limited processing metadata. It is not authoritative Staff Status storage.
- **Launchpad:** Polls Google, resolves the employee by normalized district email, checks the employee's current active state and current department, confirms department enablement, runs Staff Status validation, and creates the existing pending request.

Launchpad remains the source of truth for identity, active state, department assignment, Staff Status configuration, approval state, and absence records. No department or Launchpad identifier is accepted from the public form.

## Files

- `Code.gs` — append-only Apps Script server handlers, validation, duplicate prevention, and queue initialization.
- `Index.html` — accessible mobile-first form and submission experience.
- `appsscript.json` — V8 manifest, America/Chicago timezone, and the Sheets-only OAuth scope.
- `SETUP.md` — complete administrator setup, deployment, testing, and update instructions.

## Queue schema

The `Absence Requests` worksheet uses these stable headers:

```text
submission_uuid
submitted_at
staff_email
absence_type
duration_mode
start_date
end_date
start_time
days_value
notes
processing_status
processing_started_at
processed_at
launchpad_request_id
processing_error
processing_attempts
last_processing_attempt_at
processing_claim_id
```

The Apps Script writes a new row with `processing_status` set to `pending`. Queue-management fields are not shown by the public application. Launchpad updates only those management fields.

## Idempotency and retries

- Apps Script holds a script lock and checks `submission_uuid` before appending.
- Launchpad claims a row with a unique `processing_claim_id`.
- The Launchpad pending-request table has a unique constraint on `submission_uuid`; this is the final authority against overlapping workers.
- A stale `processing` row is eligible for recovery after the configured timeout.
- If Launchpad created the pending request but could not mark Google `processed`, the next run finds the existing UUID and repairs the queue row without creating another request.

Queue states are `pending`, `processing`, `processed`, and `error`. Validation and identity failures become `error` with a safe description. Original intake values are preserved.

## Security model

- The web app is intentionally unauthenticated so it can be used from personal phones, but every field is untrusted and validated server-side.
- Only `@sheridanschools.org` addresses are accepted; Launchpad resolves the actual current user and department later.
- The Sheet must never be shared publicly. Access is limited to appropriate administrators, the Apps Script owner, and the Launchpad service account.
- Google service-account JSON is installed outside the repository and referenced by an environment variable.
- No credential, OAuth token, internal URL, stack trace, database detail, or private-key material is written to the Sheet or rendered in Launchpad settings.

See [SETUP.md](SETUP.md) before deployment.
