from backend.app.core.config import settings
from backend.app.core.emails.base import EmailTemplate


class LoginOTPEmail(EmailTemplate):
    template_name: str = "login_otp.html"
    template_name_plain: str = "login_otp.txt"
    subject: str = "Your Login OTP"


async def send_login_otp_email(email: str, otp: str):
    context = {
        "otp": otp,
        "expiry_time": settings.ACTIVATION_TOKEN_EXPIRATION_MINUTES,
        "site_name": settings.SITE_NAME,
        "support_email": settings.SUPPORT_EMAIL,
    }

    await LoginOTPEmail.send_email(recipient=email, context=context)
