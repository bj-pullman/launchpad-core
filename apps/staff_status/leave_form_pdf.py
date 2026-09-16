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


# These baselines correspond to the blank lines printed in the canonical district PDF.
LEAVE_FORM_FIELD_POSITIONS = {
    "employee_number": TextPosition(148, 720, 420),
    "employee_name": TextPosition(148, 697, 420),
    "total_days_absent": TextPosition(148, 652, 115),
}

MONTHLY_CLASSIFICATION_LINE_POSITIONS = {
    "sick": [
        TextPosition(184, 606, 365),
        TextPosition(184, 583, 365),
        TextPosition(184, 561, 365),
        TextPosition(184, 538, 365),
    ],
    "personal": [TextPosition(184, 515, 365)],
    "vacation": [TextPosition(184, 483, 365)],
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


def _wrap_fitted_text(value: str, positions: list[TextPosition]) -> list[str]:
    words = str(value or "").split()
    lines: list[str] = []
    for position in positions:
        line = ""
        while words:
            candidate = f"{line} {words[0]}".strip()
            if line and stringWidth(candidate, "Helvetica", position.min_font_size) > position.max_width:
                break
            line = candidate
            words.pop(0)
        lines.append(line)
        if not words:
            break
    if words:
        raise LeaveFormTemplateError("Monthly absence dates do not fit within the canonical district form lines.")
    return lines


def fill_monthly_employee_leave_form(
    *,
    template_path: Path,
    output_path: Path,
    employee_number: str,
    employee_name: str,
    total_days_absent: str,
    classification_dates: dict[str, str],
) -> None:
    """Fill one monthly Central Office summary using only Sick, Personal, and Vacation lines."""

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

    overlay_buffer = BytesIO()
    overlay = canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height), pageCompression=0)
    overlay.setTitle("Monthly Employee Leave Form values")
    _draw_fitted_text(overlay, employee_number, LEAVE_FORM_FIELD_POSITIONS["employee_number"])
    _draw_fitted_text(overlay, employee_name, LEAVE_FORM_FIELD_POSITIONS["employee_name"])
    _draw_fitted_text(overlay, total_days_absent, LEAVE_FORM_FIELD_POSITIONS["total_days_absent"])
    for leave_type, positions in MONTHLY_CLASSIFICATION_LINE_POSITIONS.items():
        for value, position in zip(_wrap_fitted_text(classification_dates.get(leave_type, ""), positions), positions):
            _draw_fitted_text(overlay, value, position)
    overlay.save()
    overlay_buffer.seek(0)

    try:
        template_page.merge_page(PdfReader(overlay_buffer).pages[0], over=True)
        writer = PdfWriter()
        for page in template_reader.pages:
            writer.add_page(page)
        if template_reader.metadata:
            writer.add_metadata({key: str(value) for key, value in template_reader.metadata.items() if value is not None})
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
            "The canonical district Employee Leave Form could not be merged with the monthly absence values."
        ) from exc
