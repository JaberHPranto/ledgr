from backend.app.core.config import settings
from backend.app.core.emails.base import EmailTemplate


class ActivationEmail(EmailTemplate):
    template_name: str = "activation.html"
    template_name_plain: str = "activation.txt"
    subject: str = "Activate your account"


async def send_activation_email(email: str, token: str):
    activation_url = f"{settings.API_BASE_URL}{settings.API_V1}/auth/activate/{token}"

    context = {
        "activation_url": activation_url,
        "expiry_time": settings.ACTIVATION_TOKEN_EXPIRATION_MINUTES,
        "site_name": settings.SITE_NAME,
        "support_email": settings.SUPPORT_EMAIL,
    }

    await ActivationEmail.send_email(recipient=email, context=context)
