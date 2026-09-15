# Unified Staff Absence Apps Script Setup

Use one Apps Script project owned by a controlled district account. Publish two deployments from that same project. The private Sheet should be shared only with necessary administrators, the project owner, and the Launchpad service account.

## 1. Update the project and existing Sheet

1. In the existing Apps Script project, copy in `Code.gs`, `Index.html`, `Review.html`, `AccessDenied.html`, and `appsscript.json` from this directory.
2. Configure these Script Properties:
   - `ABSENCE_SUBMISSION_SHEET_ID`: existing private spreadsheet ID
   - `APPROVER_EMAILS`: comma-separated exact manager emails
   - `GLOBAL_APPROVER_EMAILS`: comma-separated exact global reviewer emails, or blank
3. Run `initializeAbsenceRequestSheet_` once from the Apps Script editor and authorize it. The trailing underscore prevents browser calls.
4. Verify all existing rows and the first 18 headers are unchanged. Missing review/workflow columns are appended at the end.

The initializer never recreates a populated worksheet, clears cells, reorders headers, or deletes rows. Stop if the original 18 headers are not in their established order.

## 2. Deployment A — Public Intake

1. Choose **Deploy > Manage deployments** and edit the existing public web app.
2. Select a new project version.
3. Set **Execute as** to the deploying/owner account.
4. Set access to **Anyone** / anonymous.
5. Publish and retain the existing employee `/exec` URL.

Test in a signed-out browser: the base URL must load the intake form and accept a valid district-email submission. An `action=review&id=...` URL must show Access denied without request details.

## 3. Deployment B — Reviewer Portal

1. In the same project, choose **Deploy > New deployment**.
2. Choose **Web app** and the same current project version.
3. Set **Execute as** to the deploying/owner account.
4. Restrict access to authenticated users in the Sheridan School District domain.
5. Publish and record this distinct reviewer `/exec` URL.

Do not distribute the reviewer URL as the employee form. Keep both deployment IDs and purposes in the administrator runbook. If Workspace does not offer domain-only web-app access, do not publish the reviewer deployment until that policy is available.

Deployment authentication is backed by application authorization: every review load and decision checks active Google identity, the exact allowlists, and row assignment server-side.

## 4. Launchpad configuration

In **Settings > Staff Status > Absence Form** configure:

- Spreadsheet ID and `Absence Requests` worksheet
- **Authenticated Review Web App URL:** the Deployment B `/exec` URL
- Approval manager email
- Global reviewer emails matching `GLOBAL_APPROVER_EMAILS`
- Polling interval and stale-processing timeout

Launchpad automatically appends `?action=review&id=<submission_uuid>` to the reviewer base URL in manager emails. Enable sync, save, and click **Sync Now**.

The Launchpad server continues using `STAFF_STATUS_GOOGLE_SERVICE_ACCOUNT_FILE` for outbound Google Sheets API access. Store that credential outside the repository and web-served directories.

## 5. End-to-end test

1. Submit through Deployment A at a 360–430 px phone viewport.
2. Sync and confirm Launchpad resolves the active employee's current department, creates one pending request, fills review metadata, and emails the Deployment B URL.
3. Open the review link signed out, as an unlisted user, as a listed but wrong manager, as the assigned manager, and as a global reviewer. Only the final two valid cases may see the request.
4. Confirm refreshing or opening the GET URL never changes `workflow_status`.
5. Approve once and sync. Confirm one absence, preserved reviewer audit, one employee result email, and Google synced state.
6. Deny another request and confirm no absence and one denied email.
7. Repeat polling and confirm no duplicate request, absence, or ordinary retry email.
8. Complete a request locally and confirm the next poll reconciles Google to Launchpad's final state.
9. Confirm completed requests remain visible in Launchpad's All, Approved, and Denied history filters.

## 6. Updating both deployments

Saving code does not update `/exec`. After future changes, create a new project version and edit both deployments so each uses that same new version. Retain their distinct access settings and URLs. Run the initializer after any future append-only Sheet schema change.

If Google returns a blank active-user email, reviewer access intentionally fails closed. Verify the reviewer deployment requires district sign-in and that Workspace policy permits active-user identity for the web app.
