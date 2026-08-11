import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.exceptions import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from backend.app.api.auth.models import User
from backend.app.api.auth.schema import AccountStatusSchema, UserCreateSchema
from backend.app.api.auth.utils import (
    generate_activation_token,
    generate_otp,
    generate_username,
    hash_password,
    verify_password,
)
from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.services.activation_email import send_activation_email
from backend.app.core.services.login_otp import send_login_otp_email

logger = get_logger()


class UserAuthService:
    async def get_user_by_email(
        self, email: str, session: AsyncSession, include_inactive: bool = False
    ) -> User | None:
        statement = select(User).where(User.email == email)

        if not include_inactive:
            statement = statement.where(User.is_active)

        result = await session.exec(statement)
        return result.first()

    async def get_user_by_id_no(
        self, id_no: int, session: AsyncSession, include_inactive: bool = False
    ) -> User | None:
        statement = select(User).where(User.id_no == id_no)

        if not include_inactive:
            statement = statement.where(User.is_active)

        result = await session.exec(statement)
        return result.first()

    async def get_user_by_id(
        self, id: uuid.UUID, session: AsyncSession, include_inactive: bool = False
    ) -> User | None:
        statement = select(User).where(User.id == id)

        if not include_inactive:
            statement = statement.where(User.is_active)

        result = await session.exec(statement)
        return result.first()

    async def check_user_email_exists(self, email: str, session: AsyncSession) -> bool:
        user = await self.get_user_by_email(email, session, include_inactive=True)
        return bool(user)

    async def check_user_id_no_exists(self, id_no: int, session: AsyncSession) -> bool:
        user = await self.get_user_by_id_no(id_no, session, include_inactive=True)
        return bool(user)

    async def verify_user_password(
        self, plain_password: str, hashed_password: str
    ) -> bool:
        return verify_password(plain_password, hashed_password)

    async def reset_user_state(
        self,
        user: User,
        session: AsyncSession,
        *,
        clear_otp: bool = True,
        log_action: bool = True,
    ) -> None:
        previous_status = user.account_status

        user.failed_login_attempts = 0
        user.last_failed_login = None

        if clear_otp:
            user.otp = ""
            user.otp_expiry_time = None

        if user.account_status == AccountStatusSchema.LOCKED:
            user.account_status = AccountStatusSchema.ACTIVE

        await session.commit()
        await session.refresh(user)

        if log_action and previous_status != user.account_status:
            logger.info(
                f"User {user.id} account status changed from {previous_status} to {user.account_status}"
            )

    async def validate_user_status(self, user: User) -> None:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Your account is not activated",
                    "action": "Please activate your account first",
                },
            )

        if user.account_status == AccountStatusSchema.LOCKED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Your account is locked",
                    "action": "Please contact support",
                },
            )

        if user.account_status == AccountStatusSchema.INACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Your account is inactive",
                    "action": "Please activate your account",
                },
            )

    async def generate_and_save_otp(
        self, user: User, session: AsyncSession
    ) -> tuple[bool, str]:
        try:
            otp = generate_otp()

            user.otp = otp
            user.otp_expiry_time = datetime.now(timezone.utc) + timedelta(
                minutes=settings.OTP_EXPIRATION_MINUTES
            )
            await session.commit()
            await session.refresh(user)

            for attempt in range(3):
                try:
                    await send_login_otp_email(user.email, otp)
                    logger.info(f"OTP sent successfully to {user.email}")
                    return True, otp
                except Exception as e:
                    logger.error(f"Failed to send OTP: {e}")
                    if attempt == 2:
                        user.otp = ""
                        user.otp_expiry_time = None
                        await session.commit()
                        await session.refresh(user)
                        return False, ""

                    await asyncio.sleep(2**attempt)

            return False, ""
        except Exception as e:
            logger.error(f"Failed to generate and save OTP: {e}")
            return False, ""

    async def create_user(
        self, user_data: UserCreateSchema, session: AsyncSession
    ) -> User:
        user_data_dict = user_data.model_dump(
            exclude={"confirm_password", "username", "is_active", "account_status"}
        )

        password = user_data_dict.pop("password")

        new_user = User(
            username=generate_username(),
            hashed_password=hash_password(password),
            is_active=False,
            account_status=AccountStatusSchema.PENDING,
            **user_data_dict,
        )

        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        activation_token = generate_activation_token(new_user.id)
        try:
            await send_activation_email(new_user.email, activation_token)
            logger.info(f"Activation token sent to {new_user.email}")
        except Exception as e:
            logger.error(f"Failed to send activation email: {e}")

        return new_user

    async def activate_user(self, token: str, session: AsyncSession) -> User:
        try:
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )

            if payload.get("type") != "activation":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token type"
                )

            user_id = uuid.UUID(payload.get("id"))
            user = await self.get_user_by_id(user_id, session, include_inactive=True)

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "error",
                        "message": "User not found",
                    },
                )
            if user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "error",
                        "message": "User already activated",
                    },
                )

            await self.reset_user_state(user, session, clear_otp=True, log_action=True)

            user.is_active = True
            user.account_status = AccountStatusSchema.ACTIVE

            await session.commit()
            await session.refresh(user)

            return user

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Activation token expired",
                },
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Invalid activation token",
                },
            )
        except HTTPException as http_ex:
            raise http_ex
        except Exception as e:
            logger.error(f"Failed to activate user account: {e}")
            raise

    async def verify_login_otp(
        self, email: str, otp: str, session: AsyncSession
    ) -> User:
        try:
            user = await self.get_user_by_email(email, session)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "error",
                        "message": "User not found",
                    },
                )

            await self.validate_user_status(user)
            await self.check_user_lockout(user, session)

            if not user.otp or user.otp != otp:
                await self.increment_failed_login_attempts(user, session)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "error",
                        "message": "Invalid OTP",
                    },
                )

            if user.otp_expiry_time is None or user.otp_expiry_time < datetime.now(
                timezone.utc
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "error",
                        "message": "OTP expired",
                    },
                )

            await self.reset_user_state(user, session, clear_otp=False)

            return user

        except HTTPException as http_ex:
            raise http_ex
        except Exception as e:
            logger.error(f"Error during OTP verification: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "status": "error",
                    "message": "Failed to verify OTP",
                    "action": "Please try again later",
                },
            )

    async def check_user_lockout(self, user: User, session: AsyncSession) -> None:
        if (
            user.account_status != AccountStatusSchema.LOCKED
            or user.last_failed_login is None
        ):
            return

        lockout_time = user.last_failed_login + timedelta(
            minutes=settings.LOCKOUT_DURATION_MINUTES
        )

        current_time = datetime.now(timezone.utc)

        if current_time >= lockout_time:
            await self.reset_user_state(user, session, clear_otp=False)
            logger.info(f"Lockout period ended for user {user.email}")
            return

        remaining_minutes = int(((lockout_time - current_time).total_seconds()) / 60)
        logger.warning(f"Attempted login to locked account: {user.email}")

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "error",
                "message": "Account locked",
                "action": f"Please wait {remaining_minutes} minutes before trying again",
                "lockout_remaining_minutes": remaining_minutes,
            },
        )

    async def increment_failed_login_attempts(
        self, user: User, session: AsyncSession
    ) -> None:
        user.failed_login_attempts += 1

        user.last_failed_login = datetime.now(timezone.utc)

        if user.failed_login_attempts >= settings.LOGIN_ATTEMPTS_LIMIT:
            user.account_status = AccountStatusSchema.LOCKED
            logger.warning(
                f"Account locked for user {user.email} due to too many failed login attempts"
            )

        await session.commit()
        await session.refresh(user)


user_auth_service = UserAuthService()
