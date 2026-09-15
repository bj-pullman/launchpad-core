# Staff Absence Apps Script Setup

Use a controlled district account as the Apps Script owner. The Sheet must stay private and be shared only with necessary administrators, the script owner, and the Launchpad service account.

## 1. Update the project and migrate the existing Sheet

1. Copy `Code.gs` and `Index.html` into the existing public Apps Script project.
2. Set its `ABSENCE_SUBMISSION_SHEET_ID` Script Property to the existing private spreadsheet ID.
3. Run `initializeAbsenceRequestSheet_` once from the Apps Script editor and authorize it. The trailing underscore deliberately prevents public browser calls.
4. Verify the first 18 headers and all rows are unchanged and eleven fields were appended: `staff_display_name`, `department_name`, `approval_manager_email`, `workflow_status`, `reviewed_by`, `reviewed_at`, `decision_note`, `launchpad_sync_status`, `launchpad_synced_at`, `launchpad_sync_error`, `decision_claim_id`.

The initializer never recreates a populated worksheet, clears cells, reorders headers, or deletes rows. Stop if the original 18 headers are not in their established order.

## 2. Publish the anonymous intake deployment

1. Make `appsscript.json` the active manifest.
2. Under **Deploy > Manage deployments**, edit the existing public web app and select **New version**.
3. Execute as the deploying account and allow **Anyone** / anonymous access.
4. Publish and retain the employee `/exec` URL.
5. In a signed-out browser, confirm intake works but a review URL shows Access denied.

## 3. Publish the authenticated review deployment

1. Create a second Apps Script project and copy in `staff-absence-review-form/Code.gs`, `Review.html`, `AccessDenied.html`, and `appsscript.json`.
2. Set `ABSENCE_SUBMISSION_SHEET_ID`, `APPROVER_EMAILS`, and `GLOBAL_APPROVER_EMAILS` in that project's Script Properties.
3. Create a web-app deployment that executes as the deploying account, is restricted to the district domain, and publish it.
4. Record its `/exec` URL. Never add the review source or identity scope to the anonymous public project.

The separate project is intentional: Apps Script exposes a project's public server functions to every deployment of that project. Isolation guarantees the anonymous deployment remains intake-only. Keep both project and deployment IDs in the administrator runbook. If Workspace does not offer domain-only access, do not publish review until domain restriction is available; exact-email checks remain defense in depth, not a substitute for sign-in-required deployment access.

## 4. Google service account

1. Enable Google Sheets API in a district-controlled Cloud project.
2. Create a dedicated service account and share the private Sheet directly with it as Editor.
3. Store JSON credentials outside this repository and web-served directories.
4. Set `STAFF_STATUS_GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure\launchpad\staff-absence-sheets.json` for the Launchpad service and restart it.

Never paste credentials or paths into the Sheet.

## 5. Configure Launchpad

In **Settings > Staff Status > Absence Form**, configure the spreadsheet and worksheet, authenticated review `/exec` URL, approval manager, global reviewers (matching `GLOBAL_APPROVER_EMAILS`), polling interval, and stale timeout. Enable sync, save, then click **Sync Now**. Scheduled and manual runs use the same outbound-only service.

## 6. End-to-end test

1. Submit at a 360–430 px phone viewport using a valid district email.
2. Confirm a pending row appears and contains no Launchpad data.
3. Sync. Confirm Launchpad resolves the active employee's current department, creates one pending request, fills manager/sync metadata, and sends a manager CTA to the review deployment.
4. Open the CTA signed out, unauthorized, assigned-manager, and global-reviewer. Only the authorized cases may load it.
5. Approve once. Confirm GET made no change, sync creates one absence, audit fields are retained, one employee email is sent, and Google becomes synced.
6. Deny another. Confirm no absence and one denied email.
7. Repeat polling; confirm no duplicate request, absence, or ordinary retry email.
8. Complete a request locally and confirm the next poll reconciles Google to Launchpad's final state.
9. Make `processing` or `syncing` stale beyond the timeout and confirm recovery.
10. Confirm final history remains under All/Approved/Denied in Launchpad.

## 7. Operations

Saving source does not update `/exec`; publish a new version to each affected deployment with its matching manifest. Run the initializer after future append-only schema changes.

Safe queue errors contain no tracebacks, credentials, internal URLs, or database detail. Launchpad is authoritative and repairs conflicting final state. If Google cannot provide `Session.getActiveUser().getEmail()`, review access intentionally fails closed; verify domain restriction, district sign-in, and Workspace active-user policy.
