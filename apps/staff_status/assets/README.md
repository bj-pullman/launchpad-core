# Employee Leave Form template

The canonical district Employee Leave Form is `static/forms/employee_leave_form.pdf` at the repository root. This former app-assets path is no longer used.

Launchpad preserves the original PDF and merges a transparent, dynamic-value-only overlay onto it. Overlay coordinates are maintained in `apps/staff_status/leave_form_pdf.py`; replacing the district template may require recalibrating those coordinates.

Generated employee-specific forms remain private in `instance/staff_status/generated_leave_forms/` and are served only through the authenticated, department-authorized download route. Historical generated forms are not changed automatically.
