# Staff Status

Staff Status provides department-based staff location and absence visibility.

## Leave balances and Employee Leave Forms

The Absences page includes a department-scoped **Leave Balances** modal. It lists active employees in the selected department with their employee number and Sick, Personal, and Vacation balances. Department operators and Staff Status administrators can edit these values; view-only users can see the list without edit controls. Balances are days and may contain decimals such as `8.5`, `1.25`, or `0.5`.

Initial balances are entered by an administrator. Launchpad does not infer or back-calculate them from historical absences. Sick, Personal, and Vacation are balance-tracked and map to district classifications 110, 115, and 120. Other absence classifications can still produce forms without requiring a numeric balance.

Every changed balance creates a `manual_balance_set` ledger transaction containing the old and new values and the available actor metadata. When either a public request is approved or a manager manually adds an absence, the same approved-absence service creates the absence, uses the existing Staff Status day value, deducts tracked leave, records an `absence_deduction`, snapshots the before/after balances, generates the Employee Leave Form, and sends it to the employee. A negative balance is allowed so a legitimate absence is not blocked, but the negative result and warning are persisted and displayed.

Deleting an active absence reverses a prior tracked deduction once and appends an `absence_reversal`; the original ledger entry remains. Repeated approval, delivery, PDF generation, and reversal calls use persisted state and unique ledger constraints to prevent duplicate deductions, forms, emails, or reversals. Denied requests do none of these approved-only actions.

Two canonical district templates must be deployed:

- `static/forms/vacation_personal_request_form.pdf` is used only for approved individual Personal and Vacation requests. Launchpad overlays the school year, employee details available from Identity, requested dates, persisted balance-before, days-used, balance-after values, and a Vacation/Personal selection mark. Sick and Other absences do not generate an individual PDF. Signature and approval areas remain blank.
- `static/forms/employee_leave_form.pdf` is used only by **Monthly Leave Forms** on the Absences page. An authorized department operator chooses a month and downloads a ZIP containing one Employee Leave Form per employee with Sick, Personal, or Vacation absences. The monthly report groups dates on the existing 110, 115, and 120 lines and does not alter balances, ledger entries, absences, request status, or email state.

Launchpad does not recreate either form. Each original PDF remains the visual background and receives a transparent dynamic-value overlay.

Generated Personal/Vacation request PDFs are stored privately under `instance/staff_status/generated_leave_forms/`. Monthly PDFs and ZIPs are stored privately under `instance/staff_status/monthly_leave_forms/` and are served only by the authorized generation route. Replacing either template may require recalibrating `apps/staff_status/vacation_personal_form_pdf.py` or `apps/staff_status/leave_form_pdf.py`. Existing historical generated forms are not automatically regenerated.

After every server update, verify that both PDFs exist and are readable by the Launchpad process. If a required template is absent or invalid, Launchpad logs a clear operational error and never creates a substitute form.

Approved-result email uses the configured Staff Status notification sender and existing SMTP integration. It includes leave used, balance before, remaining balance, and any negative-balance warning. Personal and Vacation emails attach their generated request form; Sick and Other approval emails have no individual form attachment. If delivery fails, the persisted error state allows the normal sync/retry path to retry without repeating accounting work.

Google absence synchronization polling is configured in seconds at **Settings > Staff Status > Absence Form**. The default and recommended interval is 60 seconds; the minimum is 30 seconds. Existing `interval_minutes` values migrate once to `interval_seconds` by multiplying by 60, so a prior five-minute interval becomes 300 seconds. The scheduler remains coalesced and limited to one running sync instance.

The Absences page groups **Add Absence**, **Reports**, **Monthly Leave Forms**, and the labeled gear **Settings** action on the right. Settings continues to open the existing Leave Balances modal.

## Core concepts

- Departments are usually derived from active users.
- Locations define where staff can mark themselves.
- Kiosk URLs allow staff to update status from shared devices.
- Board URLs display current department status.
- Absences override normal location status when active.

## Locations

Administrators can manage locations for each department. Locations support:

- Display name
- Short name
- Active/inactive state
- Drag-and-drop ordering

## Kiosk

The kiosk allows selected staff to update their status. It supports selecting one or more staff members and one or more locations.

The public kiosk includes **Light**, **Dark**, and **System** display themes. The selected preference is stored only in that browser or kiosk device using local storage. New devices default to **System**, which follows the operating system color preference and updates if it changes while the kiosk is open. This public-device setting is independent of any signed-in Launchpad user's theme preference.

### Tablet behavior

For iPads and tablets, the staff selector should be collapsible so locations remain easy to access. Users can open the staff picker, search/select staff, then choose locations and submit.

## Boards

The department board displays staff statuses and updates on an interval. It should avoid full-page refreshes and use lightweight data refreshes where possible.

Public boards provide the same **Light**, **Dark**, and **System** control. The choice persists on the display device without authentication or cookies, defaults to **System**, and does not interrupt board polling or live refresh behavior.

## Public URLs

Kiosk and board URLs depend on the General Settings public base URL. If URLs are generated incorrectly, verify Settings -> General -> Public Base URL.

## Permissions

Staff Status should use department-scoped permissions so staff only operate departments they are authorized to manage.
