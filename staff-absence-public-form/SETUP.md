# Unified Staff Absence Apps Script Setup

Use one Apps Script project owned by a controlled district account. Publish two deployments from that same project. The private Sheet should be shared only with necessary administrators, the project owner, and the Launchpad service account.

## 1. Update the project and existing Sheet

1. In the existing Apps Script project, copy in `Code.gs`, `Index.html`, `Review.html`, `AccessDenied.html`, and `appsscript.json` from this directory.
2. Configure these Script Properties:
   - `ABSENCE_SUBMISSION_SHEET_ID`: existing private spreadsheet ID
   - `APPROVER_EMAILS`: comma-separated exact manager emails
   - `GLOBAL_APPROVER_EMAILS`: comma-separated exact global reviewer emails, including personal Gmail accounts when desired, or blank
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
4. Set **Who has access** to **Anyone**. In this deployment option, Anyone means any signed-in Google account, not anonymous access.
5. Publish and record this distinct reviewer `/exec` URL.

Do not select **Anyone, even anonymous** for the reviewer deployment. Do not distribute the reviewer URL as the employee form. Keep both deployment IDs and purposes in the administrator runbook.

Any signed-in Google account may reach Deployment B, but only exact addresses in the Script Properties can load or decide a request. Deployment authentication is backed by application authorization: every review load and decision checks active Google identity, the exact allowlists, and row assignment server-side. Random signed-in Gmail accounts receive Access Denied.

## 4. Launchpad configuration

In **Settings > Staff Status > Absence Form** configure:

- Spreadsheet ID and `Absence Requests` worksheet
- **Authenticated Review Web App URL:** the Deployment B `/exec` URL
- Approval manager email
- Global reviewer emails matching `GLOBAL_APPROVER_EMAILS`, including any intentionally authorized personal Gmail account
- Polling interval and stale-processing timeout

Launchpad automatically appends `?action=review&id=<submission_uuid>` to the reviewer base URL in manager emails. Enable sync, save, and click **Sync Now**.

The Launchpad server continues using `STAFF_STATUS_GOOGLE_SERVICE_ACCOUNT_FILE` for outbound Google Sheets API access. Store that credential outside the repository and web-served directories.

## 5. End-to-end test

1. Submit through Deployment A at a 360–430 px phone viewport.
2. Sync and confirm Launchpad resolves the active employee's current department, creates one pending request, fills review metadata, and emails the Deployment B URL.
3. Open the review link signed out, as a random Gmail user, as a listed but wrong manager, as the assigned district manager, and as a configured personal Gmail global reviewer. Only the final two valid cases may see the request.
4. Confirm refreshing or opening the GET URL never changes `workflow_status`.
5. Approve once and sync. Confirm one absence, preserved reviewer audit, one employee result email, and Google synced state.
6. Deny another request and confirm no absence and one denied email.
7. Repeat polling and confirm no duplicate request, absence, or ordinary retry email.
8. Complete a request locally and confirm the next poll reconciles Google to Launchpad's final state.
9. Confirm completed requests remain visible in Launchpad's All, Approved, and Denied history filters.

Before relying on a personal Gmail reviewer, perform this production check while signed into only that Gmail account. Google documents that execute-as-owner web apps may return a blank active-user email for accounts outside the owner's Workspace domain. A blank identity will correctly produce **Sign-in Required** and deny access. If this occurs, the requested execute-as-owner model cannot reliably identify that personal account without changing the deployment identity model or adding a separate OAuth design.

## 6. Updating both deployments

Saving code does not update `/exec`. After future changes, create a new project version and edit both deployments so each uses that same new version. Retain their distinct access settings and URLs. Run the initializer after any future append-only Sheet schema change.

If Google returns a blank active-user email, reviewer access intentionally fails closed. Verify the reviewer deployment uses **Anyone** (signed-in Google users), not anonymous access, and that Google can expose active-user identity for the web app. No custom OAuth flow is used.
