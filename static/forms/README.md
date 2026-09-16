# Canonical Employee Leave Form

This directory must contain both authoritative district source forms:

- `vacation_personal_request_form.pdf` — individual approved Personal and Vacation requests.
- `employee_leave_form.pdf` — on-demand monthly employee summaries for Sick, Personal, and Vacation.

Launchpad overlays known values onto each original first page and does not recreate either form. Coordinate mappings are in `apps/staff_status/vacation_personal_form_pdf.py` and `apps/staff_status/leave_form_pdf.py`; replacing a source PDF may require recalibration.

This directory contains only the blank canonical template. Generated employee-specific forms are private and belong in `instance/staff_status/generated_leave_forms/`; historical forms are not regenerated automatically.

Deployment check: after pulling an update, verify that both PDF files exist and are readable by the Launchpad process.
