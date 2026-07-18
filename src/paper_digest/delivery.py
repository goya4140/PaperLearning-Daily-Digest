from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


SMTP = {
    "163": ("smtp.163.com", 465, True),
    "qq": ("smtp.qq.com", 465, True),
    "gmail": ("smtp.gmail.com", 587, False),
}


def resolve_provider(provider: str, sender: str) -> str:
    if provider != "auto":
        return provider
    domain = sender.rsplit("@", 1)[-1].casefold()
    if domain in {"gmail.com", "googlemail.com"}:
        return "gmail"
    if domain == "qq.com":
        return "qq"
    if domain in {"163.com", "126.com"}:
        return "163"
    raise ValueError(f"cannot infer SMTP provider from sender domain: {domain}")


def send_email(html: str, subject: str, provider: str) -> None:
    sender = os.environ.get("EMAIL_USER", "").strip()
    password = os.environ.get("EMAIL_PASS", "").strip()
    recipients = [value.strip() for value in os.environ.get("EMAIL_TO", "").split(",") if value.strip()]
    if not sender or not password or not recipients:
        raise RuntimeError("EMAIL_USER, EMAIL_PASS and EMAIL_TO are required for delivery")
    provider = resolve_provider(provider, sender)
    if provider not in SMTP:
        raise ValueError(f"unsupported SMTP provider: {provider}")
    host, port, use_ssl = SMTP[provider]
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(html, "html", "utf-8"))
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, recipients, message.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipients, message.as_string())
