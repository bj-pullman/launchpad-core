# Employee Leave Form template

The canonical district PDFs are `static/forms/vacation_personal_request_form.pdf` for individual Personal/Vacation requests and `static/forms/employee_leave_form.pdf` for monthly summaries. This former app-assets path is no longer used.

Launchpad preserves each original PDF and merges a transparent, dynamic-value-only overlay onto it. Overlay coordinates are maintained in `apps/staff_status/vacation_personal_form_pdf.py` and `apps/staff_status/leave_form_pdf.py`; replacing either district template may require recalibrating those coordinates.

Generated employee-specific forms remain private in `instance/staff_status/generated_leave_forms/` and are served only through the authenticated, department-authorized download route. Historical generated forms are not changed automatically.
