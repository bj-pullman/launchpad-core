"""Overlay approved Personal/Vacation values on the canonical district request form.

Coordinates are maintained for ``static/forms/vacation_personal_request_form.pdf``.
The source PDF is never redrawn. Replacing it requires visual coordinate verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .leave_form_pdf import LeaveFormTemplateError


@dataclass(frozen=True)
class TextPosition:
    x: float
    y: float
    max_width: float
    font_size: float = 10.0
    min_font_size: float = 7.0


# Calibrated to the blank lines in static/forms/vacation_personal_request_form.pdf (612 x 792 points).
REQUEST_FORM_FIELD_POSITIONS = {
    "school_year": TextPosition(289, 691, 95),
    "employee_name": TextPosition(132, 578, 245),
    "request_date": TextPosition(415, 578, 150),
    "position": TextPosition(82, 545, 295),
    "campus": TextPosition(432, 545, 135),
    "requested_dates": TextPosition(317, 483, 245),
    "balance_before": TextPosition(286, 453, 70),
    "days_requested": TextPosition(285, 424, 70),
    "balance_after": TextPosition(285, 396, 70),
}

REQUEST_TYPE_MARKS = {
    "vacation": (151, 512, 51, 19),
    "personal": (226, 512, 52, 19),
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


def fill_vacation_personal_request_form(
    *, template_path: Path, output_path: Path, leave_type: str, school_year: str,
    employee_name: str, request_date: str, position: str, campus: str,
    requested_dates: str, balance_before: str, days_requested: str, balance_after: str,
) -> None:
    normalized_type = str(leave_type or "").strip().lower()
    if normalized_type not in REQUEST_TYPE_MARKS:
        raise LeaveFormTemplateError("The Personal/Vacation Request Form only supports personal and vacation leave.")
    try:
        reader = PdfReader(str(template_path))
        if not reader.pages:
            raise LeaveFormTemplateError("The canonical Personal/Vacation Request Form has no pages.")
        page = reader.pages[0]
        width, height = float(page.mediabox.width), float(page.mediabox.height)
    except LeaveFormTemplateError:
        raise
    except Exception as exc:
        raise LeaveFormTemplateError(
            f"The canonical Personal/Vacation Request Form could not be opened at {template_path}."
        ) from exc

    overlay_buffer = BytesIO()
    overlay = canvas.Canvas(overlay_buffer, pagesize=(width, height), pageCompression=0)
    values = {
        "school_year": school_year, "employee_name": employee_name, "request_date": request_date,
        "position": position, "campus": campus, "requested_dates": requested_dates,
        "balance_before": balance_before, "days_requested": days_requested, "balance_after": balance_after,
    }
    for field_name, value in values.items():
        _draw_fitted_text(overlay, value, REQUEST_FORM_FIELD_POSITIONS[field_name])
    mark_x, mark_y, mark_width, mark_height = REQUEST_TYPE_MARKS[normalized_type]
    overlay.setLineWidth(1.5)
    overlay.ellipse(mark_x, mark_y, mark_x + mark_width, mark_y + mark_height, stroke=1, fill=0)
    overlay.save()
    overlay_buffer.seek(0)

    try:
        page.merge_page(PdfReader(overlay_buffer).pages[0], over=True)
        writer = PdfWriter()
        for source_page in reader.pages:
            writer.add_page(source_page)
        if reader.metadata:
            writer.add_metadata({key: str(value) for key, value in reader.metadata.items() if value is not None})
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
            "The canonical Personal/Vacation Request Form could not be merged with the approved absence values."
        ) from exc
