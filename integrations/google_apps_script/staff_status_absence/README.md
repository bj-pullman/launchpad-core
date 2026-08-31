# Staff Status Absence Google Apps Script

This folder contains the public Google Apps Script form for Staff Status absence requests. The browser page talks only to Apps Script. Apps Script sends the request to Launchpad with a bearer secret stored in Script Properties.

## Files

- `Code.gs`: server-side Apps Script handlers and Launchpad API submission.
- `Index.html`: responsive public form.

## Setup

1. Create a Google Apps Script project.
2. Add `Code.gs` and `Index.html` from this folder.
3. Open Project Settings, then Script Properties.
4. Add `LAUNCHPAD_API_URL` with the endpoint shown in Launchpad Staff Status Settings.
5. Add `LAUNCHPAD_API_SECRET` with the secret generated in Launchpad Staff Status Settings.
6. Deploy as a Web App.
7. Set "Execute as" to the script owner or a controlled service account.
8. Set access according to district policy, usually "Anyone with the link" for a public staff form.
9. Copy the `/exec` Web App URL into Launchpad Staff Status Settings as the Apps Script Web App URL.
10. Enable Apps Script absence requests in Launchpad Staff Status Settings.

## Testing

Submit a test request with a known active staff email whose department is enabled for Staff Status. The form should show:

`Your absence request has been submitted for approval.`

The approval manager should receive a review email. Approving the request in Launchpad creates the absence record and preserves the selected start time for partial-day requests.

## Secret Rotation

Rotate the Launchpad integration secret from Staff Status Settings, replace `LAUNCHPAD_API_SECRET` in Script Properties, and save. The previous secret will stop working once the new one is stored.
