import asyncio

from fastapi_mail import MessageSchema, MessageType, MultipartSubtypeEnum

from backend.app.core.celery_app import celery_app
from backend.app.core.emails.config import fastmail
from backend.app.core.logging import get_logger

logger = get_logger()


@celery_app.task(
    name="send_email",
    bind=True,
    max_retries=3,
    soft_time_limit=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
)
def send_email_task(
    self, *, recipients: list[str], subject: str, html_content: str, plain_content: str
) -> bool:
    try:
        message = MessageSchema(
            subject=subject,
            recipients=recipients,
            body=html_content,
            alternative_body=plain_content,
            subtype=MessageType.html,
            multipart_subtype=MultipartSubtypeEnum.alternative,
        )

        asyncio.run(fastmail.send_message(message))
        logger.info(f"Email sent to {recipients}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise
