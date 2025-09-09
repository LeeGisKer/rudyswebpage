import os
import smtplib
from email.message import EmailMessage
from flask import Flask, request, redirect, send_from_directory, abort

try:
    # Optional: load environment variables from .env if available
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()  # noqa: F401
except Exception:
    pass


app = Flask(__name__, static_folder='.', static_url_path='')


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    return val if (val is not None and val != "") else default


def send_email(name: str, email: str, phone: str | None, message: str) -> None:
    smtp_host = _env('MAIL_SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(_env('MAIL_SMTP_PORT', '587') or '587')
    smtp_user = _env('MAIL_SMTP_USER')
    smtp_pass = _env('MAIL_SMTP_PASS')
    to_addr = _env('MAIL_TO')
    from_addr = _env('MAIL_FROM', smtp_user or 'no-reply@localhost')

    if not (smtp_host and smtp_port and smtp_user and smtp_pass and to_addr and from_addr):
        app.logger.error('Email not sent: missing SMTP configuration')
        return

    subject = f"New estimate request from {name}"
    body_lines = [
        "A new lead was submitted from the website:",
        "",
        f"Name:   {name}",
        f"Email:  {email}",
        f"Phone:  {phone or '-'}",
        "",
        "Message:",
        message,
    ]
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to_addr
    # Make it easy to reply directly to the lead
    msg['Reply-To'] = email
    msg['X-Form-Endpoint'] = 'rudyswebpage/send'
    msg.set_content("\n".join(body_lines))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        app.logger.info('Lead email sent to %s', to_addr)


@app.route('/send', methods=['POST'])
def handle_send():
    # Simple honeypot: bots often fill hidden fields
    hp = request.form.get('company', '').strip()
    if hp:
        app.logger.info('Honeypot triggered; dropping submission')
        return redirect('/thanks', code=303)

    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    message = (request.form.get('message') or '').strip()

    # Basic validation
    if not name or not email or not message:
        app.logger.warning('Invalid submission (missing required fields)')
        return abort(400, description='Missing required fields')

    try:
        send_email(name=name, email=email, phone=phone, message=message)
    except Exception as e:
        app.logger.exception('Failed to send email: %s', e)
        # Redirect to thanks anyway to avoid leaking info to bots
        return redirect('/thanks', code=303)

    return redirect('/thanks', code=303)


@app.route('/thanks', methods=['GET'])
def thanks():
    # Serve the static thank-you page
    return send_from_directory('.', 'thanks.html')


@app.route('/')
def root_index():
    # Serve the static index
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')))  # nosec: B104

