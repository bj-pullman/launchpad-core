# Canonical Employee Leave Form

`employee_leave_form.pdf` is the authoritative district Employee Leave Form used by Staff Status.

Launchpad overlays only approved employee and absence values onto the original first page. It does not recreate the form. The coordinate mapping is in `apps/staff_status/leave_form_pdf.py` and may need recalibration whenever the district replaces this PDF.

This directory contains only the blank canonical template. Generated employee-specific forms are private and belong in `instance/staff_status/generated_leave_forms/`; historical forms are not regenerated automatically.

Deployment check: after pulling an update, verify that `static/forms/employee_leave_form.pdf` exists and is readable by the Launchpad process.
