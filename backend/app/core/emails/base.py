from jinja2 import Environment, FileSystemLoader

from backend.app.core.emails.config import TEMPLATES_DIR
from backend.app.core.emails.tasks import send_email_task
from backend.app.core.logging import get_logger

logger = get_logger()

email_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)


class EmailTemplate:
    template_name: str
    template_name_plain: str
    subject: str

    @classmethod
    async def send_email(
        cls,
        recipient: str | list[str],
        context: dict,
        subject_override: str | None = None,
    ):
        try:
            recipient_list = recipient if isinstance(recipient, list) else [recipient]

            if not cls.template_name or not cls.template_name_plain:
                raise ValueError(
                    "Both template_name and template_name_plain must be set"
                )

            html_template = email_env.get_template(cls.template_name)
            plain_template = email_env.get_template(cls.template_name_plain)

            html_content = html_template.render(**context)
            plain_content = plain_template.render(**context)

            task = send_email_task.delay(  # pyright: ignore[reportFunctionMemberAccess]
                recipients=recipient_list,
                subject=subject_override or cls.subject,
                html_content=html_content,
                plain_content=plain_content,
            )

            logger.info(f"Email task {task.id} queued for: {recipient_list}")

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
