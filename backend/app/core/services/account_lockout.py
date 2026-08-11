from datetime import datetime, timedelta

from backend.app.core.config import settings
from backend.app.core.emails.base import EmailTemplate


class AccountLockoutEmail(EmailTemplate):
    template_name: str = "account_lockout.html"
    template_name_plain: str = "account_lockout.txt"
    subject: str = "Account Security Alert - Temporary Lock"


async def send_account_lockout_email(email: str, lockout_time: datetime):
    unlock_time = lockout_time + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)

    context = {
        "lockout_duration": settings.LOCKOUT_DURATION_MINUTES,
        "lockout_time": lockout_time.strftime("%Y-%m-%d %H:%M:%S"),
        "unlock_time": unlock_time.strftime("%Y-%m-%d %H:%M:%S"),
        "site_name": settings.SITE_NAME,
        "support_email": settings.SUPPORT_EMAIL,
    }

    await AccountLockoutEmail.send_email(recipient=email, context=context)
