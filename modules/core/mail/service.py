import mimetypes
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from modules.core.settings.settings_service import get_setting, get_bool_setting


def _mail_settings():
    return {
        "enabled": get_bool_setting("mail.enabled", False),
        "smtp_host": (get_setting("mail.smtp_host", "") or "").strip(),
        "smtp_port": int((get_setting("mail.smtp_port", "587") or "587").strip()),
        "smtp_username": (get_setting("mail.smtp_username", "") or "").strip(),
        "smtp_password": (get_setting("mail.smtp_password", "") or "").strip(),
        "smtp_use_tls": get_bool_setting("mail.smtp_use_tls", True),
        "from_name": (get_setting("mail.from_name", "") or "").strip(),
    }


def send_mail(
    *,
    sender_email: str,
    recipient_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    inline_images: list[dict] | None = None,
):
    settings = _mail_settings()

    if not settings["enabled"]:
        raise ValueError("Email delivery is disabled in Integration settings.")

    if not settings["smtp_host"]:
        raise ValueError("SMTP host is not configured.")

    if not sender_email:
        raise ValueError("Sender email is required.")

    if not recipient_email:
        raise ValueError("Recipient email is required.")

    message = EmailMessage()
    message["Subject"] = subject

    from_name = settings["from_name"]
    if from_name:
        message["From"] = f"{from_name} <{sender_email}>"
    else:
        message["From"] = sender_email

    message["To"] = recipient_email
    message.set_content(text_body or "")

    if html_body:
        message.add_alternative(html_body, subtype="html")

        if inline_images:
            html_part = message.get_payload()[-1]

            for image in inline_images:
                path = image.get("path")
                cid = image.get("cid")
                filename = image.get("filename")

                if not path or not cid:
                    continue

                mime_type, _ = mimetypes.guess_type(str(path))
                if not mime_type or not mime_type.startswith("image/"):
                    continue

                maintype, subtype = mime_type.split("/", 1)

                with open(path, "rb") as f:
                    image_bytes = f.read()

                html_part.add_related(
                    image_bytes,
                    maintype=maintype,
                    subtype=subtype,
                    cid=f"<{cid}>",
                    filename=filename or Path(path).name,
                    disposition="inline",
                )

    with smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=20) as server:
        if settings["smtp_use_tls"]:
            server.starttls()

        if settings["smtp_username"] and settings["smtp_password"]:
            server.login(settings["smtp_username"], settings["smtp_password"])

        server.send_message(message)


def make_inline_image(path: str | Path) -> dict | None:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None

    cid = make_msgid(domain="launchpad.local")[1:-1]

    return {
        "path": file_path,
        "cid": cid,
        "filename": file_path.name,
    }