import httpx
import os

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = "noreply@takealook.co.kr"


def send_verification_email(to_email: str, code: str) -> None:
    body = f"""안녕하세요, OAAS입니다.

아래 인증 코드를 입력해 주세요. (유효시간 10분)

인증 코드: {code}

본인이 요청하지 않았다면 이 메일을 무시하세요."""

    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        json={
            "from": FROM_EMAIL,
            "to": [to_email],
            "subject": "[OAAS] 이메일 인증 코드",
            "text": body,
        },
    )
    response.raise_for_status()
