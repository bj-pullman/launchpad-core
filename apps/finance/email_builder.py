from pathlib import Path

from modules.core.settings.settings_service import get_setting
from modules.core.mail.service import make_inline_image


def render_finance_subject(subject_template: str, preview_context: dict, subject_prefix: str = "") -> str:
    subject = subject_template or ""
    for key, value in preview_context.items():
        subject = subject.replace(f"{{{{ {key} }}}}", str(value or "—"))

    subject = subject.strip() or "Finance Notification"

    prefix = (subject_prefix or "").strip()
    if prefix:
        return f"{prefix}: {subject}"
    return subject


def build_finance_text_body(
    *,
    header: str,
    intro: str,
    footer: str,
    preview_lines: list[dict],
) -> str:
    lines = []

    if header:
        lines.append(header)
        lines.append("")

    if intro:
        lines.append(intro)
        lines.append("")

    for item in preview_lines:
        label = item.get("label", "")
        value = item.get("value", "—")
        lines.append(f"{label}: {value}")

    if footer:
        lines.append("")
        lines.append(footer)

    return "\n".join(lines).strip()


def build_finance_html_body(
    *,
    header: str,
    intro: str,
    footer: str,
    preview_lines: list[dict],
    logo_cid: str = "",
    logo_width: str = "180",
) -> str:
    rows = []

    for item in preview_lines:
        label = item.get("label", "")
        value = item.get("value", "—")
        is_link = item.get("is_link", False)

        if is_link:
            value_html = f'<a href="{value}" target="_blank" rel="noopener noreferrer" style="color:#2563eb; text-decoration:underline;">{value}</a>'
        else:
            value_html = str(value)

        rows.append(
            f"""
            <tr>
              <td style="padding:10px 14px; font-weight:600; color:#0f172a; vertical-align:top; width:190px; border-bottom:1px solid #e2e8f0;">
                {label}
              </td>
              <td style="padding:10px 14px; color:#334155; vertical-align:top; border-bottom:1px solid #e2e8f0;">
                {value_html}
              </td>
            </tr>
            """
        )

    logo_block = ""
    if logo_cid:
        logo_block = f"""
        <div style="margin-bottom:20px;">
          <img src="cid:{logo_cid}" alt="Logo" style="max-width:{logo_width}px; height:auto; display:block;">
        </div>
        """

    return f"""
    <html>
      <body style="margin:0; padding:24px; background:#f1f5f9; font-family:Arial, Helvetica, sans-serif; color:#0f172a;">
        <div style="max-width:760px; margin:0 auto; background:#ffffff; border:1px solid #dbe4ee; border-radius:16px; overflow:hidden;">
          <div style="padding:28px;">
            {logo_block}
            <h1 style="margin:0 0 14px; font-size:24px; line-height:1.2; color:#0f172a;">
              {header or "Finance Notification"}
            </h1>
            <p style="margin:0 0 20px; font-size:15px; line-height:1.6; color:#475569;">
              {intro or ""}
            </p>
            <table style="width:100%; border-collapse:collapse; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; background:#ffffff;">
              <tbody>
                {''.join(rows)}
              </tbody>
            </table>
            <div style="margin-top:22px; padding-top:16px; border-top:1px solid #e2e8f0; font-size:13px; line-height:1.6; color:#64748b;">
              {footer or ""}
            </div>
          </div>
        </div>
      </body>
    </html>
    """


def finance_logo_inline_image() -> dict | None:
    logo_path = (get_setting("finance.notifications.logo_path", "") or "").strip()
    if not logo_path:
        return None

    base_dir = Path(__file__).resolve().parents[2]
    absolute_path = base_dir / "static" / logo_path
    return make_inline_image(absolute_path)