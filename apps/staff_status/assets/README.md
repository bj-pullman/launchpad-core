# Employee Leave Form template

Generated leave forms are private server-side artifacts. Launchpad currently recreates the district Employee Leave Form with ReportLab because the approved request did not include the source PDF binary.

The reserved replacement path is `employee_leave_form.pdf` in this directory. A future template update should keep that filename and update `generate_employee_leave_form()` in `apps/staff_status/service.py` with the matching field names or overlay coordinates. Never place generated employee forms in this directory or under `static/`; generated files belong in `instance/staff_status/generated_leave_forms/` and are served only through the authenticated download route.

Replacing the source format must not change leave deductions, ledger entries, historical balance snapshots, or email idempotency.
