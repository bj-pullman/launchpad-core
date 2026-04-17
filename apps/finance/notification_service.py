import smtplib
from email.message import EmailMessage

from modules.core.settings.settings_service import get_setting, get_bool_setting


def _render_subject(subject_template: str, preview_context: dict, subject_prefix: str = "") -> str:
    subject = subject_template or ""
    for key, value in preview_context.items():
        subject = subject.replace(f"{{{{ {key} }}}}", str(value or "—"))

    subject = subject.strip() or "Finance Notification"

    prefix = (subject_prefix or "").strip()
    if prefix:
        return f"{prefix}: {subject}"
    return subject


def _build_body(
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


def send_finance_test_email(
    *,
    sender_email: str,
    recipient_email: str,
    subject_template: str,
    subject_prefix: str,
    template_header: str,
    template_intro: str,
    template_footer: str,
    preview_context: dict,
    preview_lines: list[dict],
):
    mail_enabled = get_bool_setting("mail.enabled", False)
    smtp_host = (get_setting("mail.smtp_host", "") or "").strip()
    smtp_port = int((get_setting("mail.smtp_port", "587") or "587").strip())
    smtp_username = (get_setting("mail.smtp_username", "") or "").strip()
    smtp_password = (get_setting("mail.smtp_password", "") or "").strip()
    smtp_use_tls = get_bool_setting("mail.smtp_use_tls", True)

    if not mail_enabled:
        raise ValueError("Email delivery is disabled in Integration settings.")

    if not smtp_host:
        raise ValueError("SMTP host is not configured.")
    if not sender_email:
        raise ValueError("Sender email is required.")
    if not recipient_email:
        raise ValueError("Test recipient email is required.")

    subject = _render_subject(
        subject_template=subject_template,
        preview_context=preview_context,
        subject_prefix=subject_prefix,
    )

    body = _build_body(
        header=template_header,
        intro=template_intro,
        footer=template_footer,
        preview_lines=preview_lines,
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        if smtp_use_tls:
            server.starttls()

        if smtp_username and smtp_password:
            server.login(smtp_username, smtp_password)

        server.send_message(message)