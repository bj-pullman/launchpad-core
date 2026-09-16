# Staff Status

Staff Status provides department-based staff location and absence visibility.

## Leave balances and Employee Leave Forms

The Absences page includes a department-scoped **Leave Balances** modal. It lists active employees in the selected department with their employee number and Sick, Personal, and Vacation balances. Department operators and Staff Status administrators can edit these values; view-only users can see the list without edit controls. Balances are days and may contain decimals such as `8.5`, `1.25`, or `0.5`.

Initial balances are entered by an administrator. Launchpad does not infer or back-calculate them from historical absences. Sick, Personal, and Vacation are balance-tracked and map to district classifications 110, 115, and 120. Other absence classifications can still produce forms without requiring a numeric balance.

Every changed balance creates a `manual_balance_set` ledger transaction containing the old and new values and the available actor metadata. When either a public request is approved or a manager manually adds an absence, the same approved-absence service creates the absence, uses the existing Staff Status day value, deducts tracked leave, records an `absence_deduction`, snapshots the before/after balances, generates the Employee Leave Form, and sends it to the employee. A negative balance is allowed so a legitimate absence is not blocked, but the negative result and warning are persisted and displayed.

Deleting an active absence reverses a prior tracked deduction once and appends an `absence_reversal`; the original ledger entry remains. Repeated approval, delivery, PDF generation, and reversal calls use persisted state and unique ledger constraints to prevent duplicate deductions, forms, emails, or reversals. Denied requests do none of these approved-only actions.

The canonical district Employee Leave Form must be deployed at `static/forms/employee_leave_form.pdf`. Launchpad does not recreate or redesign the form: it preserves the original PDF as the background and overlays only the employee number, employee name, total approved days, and date/date range on the applicable printed district classification line. Employee and supervisor signature/date lines remain blank.

Generated employee-specific PDFs are stored outside public static assets under `instance/staff_status/generated_leave_forms/` and are available only through the authenticated, department-authorized download route. Replacing the canonical template may require recalibrating the named coordinates in `apps/staff_status/leave_form_pdf.py`. Existing historical generated forms are not automatically regenerated.

After every server update, verify that `static/forms/employee_leave_form.pdf` exists and is readable by the Launchpad process. If the template is absent or invalid, Launchpad logs a clear generation error and does not create a substitute form or send a recreated PDF.

Approved-result email uses the configured Staff Status notification sender and existing SMTP integration. It attaches the PDF and includes leave used, balance before, remaining balance, and any negative-balance warning. If delivery fails, the persisted error state allows the normal sync/retry path to retry without repeating accounting work.

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

### Tablet behavior

For iPads and tablets, the staff selector should be collapsible so locations remain easy to access. Users can open the staff picker, search/select staff, then choose locations and submit.

## Boards

The department board displays staff statuses and updates on an interval. It should avoid full-page refreshes and use lightweight data refreshes where possible.

## Public URLs

Kiosk and board URLs depend on the General Settings public base URL. If URLs are generated incorrectly, verify Settings -> General -> Public Base URL.

## Permissions

Staff Status should use department-scoped permissions so staff only operate departments they are authorized to manage.
