from backend.app.core.config import settings
from backend.app.core.emails.base import EmailTemplate


class BankAccountCreatedEmail(EmailTemplate):
    template_name: str = "account_created.html"
    template_name_plain: str = "account_created.txt"
    subject: str = "Welcome to Ledgr - Your Account is Ready"


async def send_bank_account_created_email(
    email: str,
    full_name: str,
    account_number: str,
    account_name: str,
    account_type: str,
    currency: str,
    identification_type: str,
):
    context = {
        "full_name": full_name,
        "account_number": account_number,
        "account_name": account_name,
        "account_type": account_type,
        "currency": currency,
        "identification_type": identification_type,
        "site_name": settings.SITE_NAME,
        "support_email": settings.SUPPORT_EMAIL,
    }

    await BankAccountCreatedEmail.send_email(recipient=email, context=context)
