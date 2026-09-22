"""Send finished reports to a supplied address. No accounts, no mailing list.

SMTP is optional: if host/from are missing the send is skipped and the report
is still available on the site for REPORT_TTL_MINUTES. Tests inspect `outbox`.
"""
from __future__ import annotations

import json
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from app.config import settings

_log = logging.getLogger("creatorintel.mail")

# Local-part @ domain.tld — rejects spaces and missing dots, not a full RFC parser.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

outbox: list[dict] = []


def normalize_email(value: str | None) -> str:
    addr = (value or "").strip().lower()
    if not addr or not _EMAIL.match(addr) or len(addr) > 254:
        return ""
    return addr


def configured() -> bool:
    return bool(settings.smtp_host and (settings.smtp_from or settings.smtp_user))


def _desk_excerpt(report) -> tuple[str, str]:
    """one_liner, job from stored payload. Empty when the pack has no desk."""
    raw = getattr(report, "payload_json", None) or ""
    if not raw:
        return "", ""
    try:
        data = json.loads(raw)
    except ValueError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    desk = data.get("desk") or {}
    if not isinstance(desk, dict):
        return "", ""
    return str(desk.get("one_liner") or "").strip(), str(desk.get("job") or "").strip()


def compose_bodies(report, public_base: str = "") -> tuple[str, str]:
    """Plain + HTML bodies. Desk lines are copied from the payload, never invented."""
    ttl = settings.report_ttl_label
    base = (public_base or settings.public_base_url).rstrip("/")
    slug = report.share_slug
    name = report.subject_name
    one, job = _desk_excerpt(report)
    text = (
        f"Your OMNISCOPE report for {name} is attached.\n\n"
    )
    if one:
        text += f"{one}\n"
    if job:
        text += f"This week's job: {job}\n"
    if one or job:
        text += "\n"
    text += (
        f"It is also on the website for {ttl}, then it is deleted:\n"
        f"  {base}/r/{slug}\n"
        f"  {base}/r/{slug}.html\n"
        "Download the attachments now if you need a copy.\n\n"
        "This address is not stored as an account. We only used it to send this email.\n"
    )
    desk_html = ""
    if one:
        desk_html += f"<p style=\"margin:0 0 12px;font-size:16px;line-height:1.45\">{_esc(one)}</p>"
    if job:
        desk_html += (
            f"<p style=\"margin:0 0 16px;color:#9aa3ad;font-size:14px\">"
            f"This week's job: {_esc(job)}</p>"
        )
    html = (
        "<div style=\"font-family:Outfit,system-ui,sans-serif;background:#0a0c0f;"
        "color:#e8edf2;padding:28px\">"
        f"<p style=\"letter-spacing:.12em;text-transform:uppercase;color:#3dd68c;"
        f"font-size:12px;margin:0 0 16px\">OMNISCOPE</p>"
        f"<p style=\"margin:0 0 12px\">Your report for <b>{_esc(name)}</b> is attached.</p>"
        f"{desk_html}"
        f"<p style=\"margin:0 0 8px\"><a href=\"{base}/r/{slug}\" "
        f"style=\"color:#3dd68c\">Open on the site</a> · "
        f"<a href=\"{base}/r/{slug}.html\" style=\"color:#3dd68c\">Download HTML</a></p>"
        f"<p style=\"color:#9aa3ad;font-size:13px\">Available for {ttl}, then deleted. "
        "This address is not stored as an account.</p>"
        "</div>"
    )
    return text, html


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def send_report(to: str, report, public_base: str = "") -> str:
    """Attach HTML (and JSON/Word when present). Returns sent|skipped|failed."""
    addr = normalize_email(to)
    if not addr:
        return "skipped"
    html_path = Path(report.html_path) if report.html_path else None
    if html_path is None or not html_path.is_file():
        return "failed"

    subject = f"OMNISCOPE report: {report.subject_name}"
    body, html = compose_bodies(report, public_base)
    attachments: list[tuple[str, str, bytes]] = []
    attachments.append((f"{report.share_slug}.html", "text/html", html_path.read_bytes()))
    if report.payload_json:
        attachments.append((f"{report.share_slug}.json", "application/json",
                            report.payload_json.encode("utf-8")))
    if report.docx_path and Path(report.docx_path).is_file():
        attachments.append((
            f"{report.share_slug}.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            Path(report.docx_path).read_bytes(),
        ))

    record = {"to": addr, "subject": subject, "files": [a[0] for a in attachments],
              "preview": body[:240]}
    outbox.append(record)

    if not configured():
        _log.warning("SMTP is not configured; report email skipped")
        return "skipped"
    try:
        _transmit(addr, subject, body, html, attachments)
    except Exception:
        try:
            _transmit(addr, subject, body, html, attachments)
        except Exception:
            _log.warning("report email failed",
                         extra={"to_domain": addr.rsplit("@", 1)[-1]},
                         exc_info=True)
            return "failed"
    return "sent"


def _use_ssl(port: int) -> bool:
    """465 = implicit SSL. 587 = STARTTLS even when smtp_secure is on."""
    if port == 587:
        return False
    return bool(settings.smtp_secure)


def _transmit(to: str, subject: str, body: str, html: str,
              attachments: list[tuple[str, str, bytes]]) -> None:
    sender = settings.smtp_from or settings.smtp_user
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, mime, data in attachments:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype or "application",
                           subtype=subtype or "octet-stream", filename=name)

    host = settings.smtp_host
    port = int(settings.smtp_port or 465)
    context = ssl.create_default_context()
    if _use_ssl(port):
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
