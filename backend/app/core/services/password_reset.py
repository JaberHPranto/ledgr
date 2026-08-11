import uuid

from backend.app.api.auth.utils import create_password_reset_token
from backend.app.core.config import settings
from backend.app.core.emails.base import EmailTemplate


class PasswordResetEmail(EmailTemplate):
    template_name: str = "password_reset.html"
    template_name_plain: str = "password_reset.txt"
    subject: str = "Reset Your Password"


async def send_password_reset_email(email: str, user_id: uuid.UUID):
    reset_token = create_password_reset_token(user_id)

    reset_url = (
        f"{settings.API_BASE_URL}{settings.API_V1}/auth/reset-password/{reset_token}"
    )

    context = {
        "reset_url": reset_url,
        "expiry_time": settings.PASSWORD_RESET_TOKEN_EXPIRATION_MINUTES,
        "site_name": settings.SITE_NAME,
        "support_email": settings.SUPPORT_EMAIL,
    }

    await PasswordResetEmail.send_email(recipient=email, context=context)
