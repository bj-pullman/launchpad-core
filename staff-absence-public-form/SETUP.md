# Staff Absence Public Form Setup

Complete these steps in order. The Google Sheet is a private queue even though the Apps Script web page is public.

## A. Create and initialize the Google Sheet

1. Create a Google Sheet owned by an appropriate district account. Suggested name: **Staff Absence Requests**.
2. Copy the spreadsheet ID from the URL. In `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`, the value between `/d/` and `/edit` is the ID.
3. Do not enable public or link-based sharing for the Sheet.
4. In the Apps Script project described below, create the Script Property `ABSENCE_SUBMISSION_SHEET_ID` with this ID.
5. Run `initializeAbsenceRequestSheet` once from the Apps Script editor and authorize it.
6. Confirm that the `Absence Requests` worksheet was created with all 18 headers shown in `README.md`.

Do not rename, reorder, remove, or add columns ahead of these headers. Both Apps Script and Launchpad validate the exact schema.

## B. Create the Apps Script project

Manual setup does not require `clasp`:

1. Go to [script.google.com](https://script.google.com) with the controlled district owner account.
2. Create a new project and name it **Staff Absence Public Form**.
3. Replace the default `Code.gs` with this directory's `Code.gs`.
4. Add an HTML file named `Index` and copy in `Index.html`.
5. In Project Settings, enable display of the `appsscript.json` manifest and replace it with this directory's manifest.
6. Under Script Properties, add `ABSENCE_SUBMISSION_SHEET_ID` with the spreadsheet ID.
7. Run `initializeAbsenceRequestSheet` and approve the requested Google Sheets permission.

Optional `clasp` workflow:

1. Install and authenticate `clasp` according to Google's official documentation.
2. Clone or initialize the Apps Script project in a separate working directory.
3. Copy these source files into that working directory and run `clasp push`.

`clasp` is optional and is not required for setup or updates.

## C. Deploy the public web app

1. In Apps Script, select **Deploy > New deployment**.
2. Choose **Web app**.
3. Set **Execute as** to the deploying/owner account.
4. Set access to **Anyone** (or the equivalent anonymous public option available to the Workspace tenant).
5. Deploy and authorize the project.
6. Use the production URL ending in `/exec` for employees.

The `/dev` URL runs the latest saved code and is available only to users with editor access; use it for development checks. The `/exec` URL runs the published deployment version and is the employee-facing URL.

Public deployment makes only the form callable. It does not make the Sheet public, and it does not create any connection to Launchpad.

## D. Create the Launchpad service account and share the Sheet

1. In a district-controlled Google Cloud project, enable the **Google Sheets API**.
2. Create a dedicated service account for the Launchpad absence sync.
3. Create and securely download a JSON key only if the server's deployment model requires a key file.
4. Obtain the service account email from Google Cloud IAM or the JSON file's `client_email` field.
5. Share the **Staff Absence Requests** Sheet directly with that service account email as **Editor**. Editor access is required because Launchpad must claim rows and write processing results.
6. Do not share the Sheet with “Anyone,” “Anyone with the link,” or a public group.

Allowed Sheet principals should be limited to appropriate district administrators, the Apps Script owner, and this service account.

## E. Install Launchpad Google credentials

1. Copy the service-account JSON file to a protected location on the private Launchpad server, outside the repository and outside any web-served directory.
2. Restrict file permissions to the Windows service identity (or operating-system account) that runs Launchpad and necessary administrators.
3. Set this environment variable for the Launchpad service:

```text
STAFF_STATUS_GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure\launchpad\staff-absence-sheets.json
```

4. Restart the Launchpad service so it receives the environment variable.

Do not put credential JSON in this repository, `.env` committed to source control, the Google Sheet, or a visible Launchpad setting. The settings page displays only `Yes` or `No` for credential availability.

## F. Configure Launchpad

1. Sign in with an account that has `launchpad.settings.staff_status.manage`.
2. Open **Settings > Staff Status > Absence Form**.
3. Enter the spreadsheet ID.
4. Enter `Absence Requests` as the worksheet name.
5. Set the polling interval (default 5 minutes) and stale-processing timeout (default 15 minutes).
6. Confirm **Google Credentials Configured** shows **Yes**.
7. Enter the existing approval manager email.
8. Enable Google absence synchronization and save.
9. Click **Sync Now**. Confirm the connection/last-run panel reports a successful sync.
10. Confirm the scheduler lists/runs `staff_status.google_absence_sync` at the configured interval in server logs.

The manual action and scheduler call the same sync service. Manual sync is intended for initial verification and troubleshooting; scheduled polling is normal operation.

## G. Test the complete workflow

1. Open the `/exec` URL on a personal phone, preferably while not signed in to a district Google account.
2. Submit a request with a valid `@sheridanschools.org` email.
3. Confirm one row appears and its status is `pending`.
4. Wait for polling or click **Sync Now**.
5. Confirm Launchpad resolves the correct current active user.
6. Confirm it uses the user's current department, not any Google-provided department.
7. Confirm a normal pending Staff Status absence request is created.
8. Confirm the Sheet row becomes `processed` and contains the pending-request ID.
9. Confirm the existing approval notification and review workflow operate normally.
10. Run sync again and confirm no second pending request is created.
11. Temporarily reproduce a stale `processing` row older than the timeout and confirm Launchpad safely reclaims or repairs it.
12. Confirm an invalid district email is rejected by Apps Script.
13. Test a valid district address that has no Launchpad user; the private queue row should become `error`.
14. Test an inactive user and confirm `error`.
15. Test a user whose current department has Staff Status disabled and confirm `error`.
16. Test all conditional duration fields and the layout at approximately 360–430 px width.
17. Confirm the Sheet itself remains inaccessible to anonymous users.
18. Confirm there is no public Launchpad absence integration route and no request from Apps Script to Launchpad.

## H. Update Apps Script

1. Make and review changes in this repository first.
2. Copy the updated files into Apps Script, or use `clasp push`.
3. Test saved code with the editor and `/dev` URL.
4. Select **Deploy > Manage deployments**, edit the production web-app deployment, and publish a **new version**.
5. Verify the existing `/exec` URL now serves the new version. Creating a new deployment instead may produce a different URL.

Changing repository files or saving editor code alone does not update an existing versioned `/exec` deployment.

## Operational notes

- Validation/identity errors are retained as `error` rows with safe descriptions. Correct the underlying Launchpad identity/configuration issue, then an authorized Sheet administrator may reset `processing_status` to `pending` for an intentional retry.
- If Launchpad loses connectivity after creating a pending request, stale recovery uses the UUID to repair the row without creating a duplicate.
- Never paste raw Google API errors, stack traces, tokens, credential paths, private keys, internal URLs, or database information into queue cells.
