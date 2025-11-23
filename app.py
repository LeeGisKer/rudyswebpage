from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from typing import Iterable

from flask import Flask, Response, abort, redirect, request, url_for

try:
    # Optional: load environment variables from .env if available
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()  # noqa: F401
except Exception:
    pass


app = Flask(__name__, static_folder='.', static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024  # keep form posts tiny


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    return val if (val is not None and val != "") else default


def _clean_header_value(raw: str, limit: int = 255) -> str:
    """
    Prevent header injection and trim excessively long user input.
    """
    cleaned = raw.replace('\r', ' ').replace('\n', ' ').strip()
    return cleaned[:limit]


def _clean_message(raw: str, limit: int = 5000) -> str:
    cleaned = raw.replace('\r\n', '\n').replace('\r', '\n').strip()
    return cleaned[:limit]


def _parse_addresses(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(addr.strip() for addr in raw.split(',') if addr.strip())


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    user: str
    password: str
    to_addrs: tuple[str, ...]
    from_addr: str

    @classmethod
    @lru_cache(maxsize=1)
    def load(cls) -> MailConfig | None:
        host = _env('MAIL_SMTP_HOST', 'smtp.gmail.com')
        port_raw = _env('MAIL_SMTP_PORT', '587')
        user = _env('MAIL_SMTP_USER')
        password = _env('MAIL_SMTP_PASS')
        to_addrs = _parse_addresses(_env('MAIL_TO'))
        from_addr = _env('MAIL_FROM', user or 'no-reply@localhost')

        if not (host and port_raw and user and password and to_addrs and from_addr):
            return None

        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            return None

        return cls(
            host=host,
            port=port,
            user=user,
            password=password,
            to_addrs=to_addrs,
            from_addr=from_addr,
        )


_config_missing_logged = False


def get_mail_config() -> MailConfig | None:
    global _config_missing_logged
    cfg = MailConfig.load()
    if cfg is None and not _config_missing_logged:
        app.logger.error('Email not sent: missing or invalid SMTP configuration')
        _config_missing_logged = True
    return cfg


def _smtp_client(cfg: MailConfig) -> smtplib.SMTP:
    if cfg.port == 465:
        server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20)
    else:
        server = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
        server.starttls()
    server.login(cfg.user, cfg.password)
    return server


def send_email(name: str, email: str, phone: str | None, message: str) -> None:
    cfg = get_mail_config()
    if cfg is None:
        return

    subject = f"New estimate request from {name}"
    body_lines: Iterable[str] = (
        "A new lead was submitted from the website:",
        "",
        f"Name:   {name}",
        f"Email:  {email}",
        f"Phone:  {phone or '-'}",
        "",
        "Message:",
        message,
    )
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = cfg.from_addr
    msg['To'] = ", ".join(cfg.to_addrs)
    # Make it easy to reply directly to the lead
    msg['Reply-To'] = email
    msg['X-Form-Endpoint'] = 'rudyswebpage/send'
    msg.set_content("\n".join(body_lines), charset='utf-8')

    with _smtp_client(cfg) as server:
        server.send_message(msg)
        app.logger.info('Lead email sent to %s', msg['To'])


@app.route('/send', methods=['POST'])
def handle_send():
    # Simple honeypot: bots often fill hidden fields
    hp = _clean_header_value(request.form.get('company', ''))
    if hp:
        app.logger.info('Honeypot triggered; dropping submission')
        return redirect(url_for('thanks'), code=303)

    name = _clean_header_value(request.form.get('name', ''))
    email = _clean_header_value(request.form.get('email', ''))
    phone = _clean_header_value(request.form.get('phone', ''))
    message = _clean_message(request.form.get('message', ''))

    # Basic validation
    if not name or not email or not message:
        app.logger.warning('Invalid submission (missing required fields)')
        return abort(400, description='Missing required fields')

    try:
        send_email(name=name, email=email, phone=phone, message=message)
    except Exception as e:
        app.logger.exception('Failed to send email: %s', e)
        # Redirect to thanks anyway to avoid leaking info to bots
        return redirect(url_for('thanks'), code=303)

    return redirect(url_for('thanks'), code=303)


@app.route('/thanks', methods=['GET'])
def thanks():
    # Serve the static thank-you page
    return app.send_static_file('thanks.html')


@app.route('/')
def root_index():
    # Serve the static index
    return app.send_static_file('index.html')


@app.after_request
def add_headers(resp: Response) -> Response:
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('Referrer-Policy', 'same-origin')
    if request.path.startswith(('/assets/', '/style.css')):
        resp.cache_control.public = True
        resp.cache_control.max_age = 86400
        resp.cache_control.immutable = True
    return resp


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')))  # nosec: B104
