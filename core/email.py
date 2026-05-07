import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_EMAIL    = os.getenv("GMAIL_EMAIL", "")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD", "")
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587


def send_verification_email(to_email: str, code: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "[OAAS] 이메일 인증 코드"
    msg["From"]    = GMAIL_EMAIL
    msg["To"]      = to_email

    body = f"""안녕하세요, OAAS입니다.

아래 인증 코드를 입력해 주세요. (유효시간 10분)

인증 코드: {code}

본인이 요청하지 않았다면 이 메일을 무시하세요."""

    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(GMAIL_EMAIL, GMAIL_PASSWORD)
        smtp.sendmail(GMAIL_EMAIL, to_email, msg.as_string())
