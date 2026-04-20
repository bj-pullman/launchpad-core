from modules.core.mail.service import send_mail
from apps.finance.email_builder import (
    render_finance_subject,
    build_finance_text_body,
    build_finance_html_body,
    finance_logo_inline_image,
)
from modules.core.settings.settings_service import get_setting


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
    logo_width = (get_setting("finance.notifications.logo_width", "180") or "180").strip()

    subject = render_finance_subject(
        subject_template=subject_template,
        preview_context=preview_context,
        subject_prefix=subject_prefix,
    )

    text_body = build_finance_text_body(
        header=template_header,
        intro=template_intro,
        footer=template_footer,
        preview_lines=preview_lines,
    )

    logo_image = finance_logo_inline_image()
    logo_cid = logo_image["cid"] if logo_image else ""

    html_body = build_finance_html_body(
        header=template_header,
        intro=template_intro,
        footer=template_footer,
        preview_lines=preview_lines,
        logo_cid=logo_cid,
        logo_width=logo_width,
    )

    inline_images = [logo_image] if logo_image else []

    send_mail(
        sender_email=sender_email,
        recipient_email=recipient_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        inline_images=inline_images,
    )