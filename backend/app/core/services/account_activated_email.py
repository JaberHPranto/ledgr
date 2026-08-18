from backend.app.core.config import settings
from backend.app.core.emails.base import EmailTemplate


class AccountActivatedEmail(EmailTemplate):
    template_name: str = "account_activated.html"
    template_name_plain: str = "account_activated.txt"
    subject: str = "Your Account is Activated"


async def send_account_activated_email(
    email: str,
    full_name: str,
    account_number: str,
    account_name: str,
    account_type: str,
    currency: str,
):
    context = {
        "full_name": full_name,
        "account_number": account_number,
        "account_name": account_name,
        "account_type": account_type,
        "currency": currency,
        "site_name": settings.SITE_NAME,
        "support_email": settings.SUPPORT_EMAIL,
    }

    await AccountActivatedEmail.send_email(recipient=email, context=context)
