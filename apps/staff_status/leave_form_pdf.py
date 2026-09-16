"""Fill the canonical district Employee Leave Form with a text-only overlay.

The coordinates in this module are calibrated to ``static/forms/employee_leave_form.pdf``.
If the district replaces that PDF, verify and, if necessary, recalibrate this mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


class LeaveFormTemplateError(RuntimeError):
    """Raised when the canonical district leave-form template cannot be used."""


@dataclass(frozen=True)
class TextPosition:
    x: float
    y: float
    max_width: float
    font_size: float = 10.0
    min_font_size: float = 7.0


@dataclass(frozen=True)
class ClassificationPosition:
    code: str
    label: str
    position: TextPosition


# These baselines correspond to the blank lines printed in the canonical district PDF.
LEAVE_FORM_FIELD_POSITIONS = {
    "employee_number": TextPosition(148, 720, 420),
    "employee_name": TextPosition(148, 697, 420),
    "total_days_absent": TextPosition(148, 652, 115),
}

DISTRICT_CLASSIFICATION_POSITIONS = {
    "sick": ClassificationPosition("110", "SICK LEAVE", TextPosition(184, 606, 365)),
    "personal": ClassificationPosition("115", "PERSONAL LEAVE", TextPosition(184, 515, 365)),
    "vacation": ClassificationPosition("120", "VACATION", TextPosition(184, 483, 365)),
    "school_business": ClassificationPosition("145", "SCHOOL BUSINESS", TextPosition(184, 451, 365)),
    "professional_development": ClassificationPosition(
        "146", "PROFESSIONAL DEVELOPMENT", TextPosition(184, 413, 365)
    ),
    "leave_without_pay": ClassificationPosition("147", "LEAVE WITHOUT PAY", TextPosition(184, 391, 365)),
    "jury_duty": ClassificationPosition("130", "JURY DUTY", TextPosition(184, 368, 365)),
    "maternity_leave": ClassificationPosition("980", "MATERNITY LEAVE", TextPosition(184, 336, 365)),
    "sick_leave_bank": ClassificationPosition("117", "SICK LEAVE BANK", TextPosition(184, 290, 365)),
    "family_leave_bank": ClassificationPosition("113", "FAMILY LEAVE BANK", TextPosition(184, 268, 365)),
    "shared_leave": ClassificationPosition("108", "SHARED LEAVE", TextPosition(184, 245, 365)),
    "military": ClassificationPosition("135", "MILITARY", TextPosition(184, 222, 365)),
}

CLASSIFICATION_ALIASES = {
    "maternity": "maternity_leave",
    "sick_bank": "sick_leave_bank",
    "family_bank": "family_leave_bank",
}


def _draw_fitted_text(pdf: canvas.Canvas, value: object, position: TextPosition) -> None:
    text = str(value or "").strip()
    if not text:
        return
    font_size = position.font_size
    while font_size > position.min_font_size and stringWidth(text, "Helvetica", font_size) > position.max_width:
        font_size = max(position.min_font_size, font_size - 0.5)
    pdf.setFont("Helvetica", font_size)
    pdf.drawString(position.x, position.y, text)


def _build_overlay(
    *,
    page_width: float,
    page_height: float,
    employee_number: str,
    employee_name: str,
    total_days_absent: str,
    classification: str,
    date_label: str,
) -> BytesIO:
    normalized_classification = CLASSIFICATION_ALIASES.get(classification, classification)
    classification_position = DISTRICT_CLASSIFICATION_POSITIONS.get(normalized_classification)
    if not classification_position:
        raise LeaveFormTemplateError(
            f"Absence classification {classification!r} is not mapped to the canonical district Employee Leave Form."
        )

    overlay_buffer = BytesIO()
    overlay = canvas.Canvas(
        overlay_buffer,
        pagesize=(page_width, page_height),
        pageCompression=0,
    )
    overlay.setTitle("Employee Leave Form values")
    _draw_fitted_text(overlay, employee_number, LEAVE_FORM_FIELD_POSITIONS["employee_number"])
    _draw_fitted_text(overlay, employee_name, LEAVE_FORM_FIELD_POSITIONS["employee_name"])
    _draw_fitted_text(overlay, total_days_absent, LEAVE_FORM_FIELD_POSITIONS["total_days_absent"])
    _draw_fitted_text(overlay, date_label, classification_position.position)
    overlay.save()
    overlay_buffer.seek(0)
    return overlay_buffer


def fill_employee_leave_form(
    *,
    template_path: Path,
    output_path: Path,
    employee_number: str,
    employee_name: str,
    total_days_absent: str,
    classification: str,
    date_label: str,
) -> None:
    """Merge dynamic values onto the original PDF without recreating its artwork."""

    try:
        template_reader = PdfReader(str(template_path))
        if not template_reader.pages:
            raise LeaveFormTemplateError("The canonical district Employee Leave Form has no pages.")
        template_page = template_reader.pages[0]
        page_width = float(template_page.mediabox.width)
        page_height = float(template_page.mediabox.height)
    except LeaveFormTemplateError:
        raise
    except Exception as exc:
        raise LeaveFormTemplateError(
            f"The canonical district Employee Leave Form could not be opened at {template_path}."
        ) from exc

    overlay_buffer = _build_overlay(
        page_width=page_width,
        page_height=page_height,
        employee_number=employee_number,
        employee_name=employee_name,
        total_days_absent=total_days_absent,
        classification=classification,
        date_label=date_label,
    )

    try:
        overlay_page = PdfReader(overlay_buffer).pages[0]
        template_page.merge_page(overlay_page, over=True)
        writer = PdfWriter()
        for page in template_reader.pages:
            writer.add_page(page)
        if template_reader.metadata:
            writer.add_metadata(
                {key: str(value) for key, value in template_reader.metadata.items() if value is not None}
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(f".{output_path.name}.tmp")
        try:
            with temporary_path.open("wb") as output_file:
                writer.write(output_file)
            temporary_path.replace(output_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except Exception as exc:
        raise LeaveFormTemplateError(
            "The canonical district Employee Leave Form could not be merged with the approved absence values."
        ) from exc
