import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import any_, desc, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.auth.models import User
from backend.app.api.auth.utils import generate_otp
from backend.app.api.bank_account.enums import AccountStatusEnum
from backend.app.api.bank_account.models import BankAccount
from backend.app.api.bank_account.utils import calculate_conversion
from backend.app.api.transactions.enums import (
    TransactionCategoryEnum,
    TransactionFailureReason,
    TransactionStatusEnum,
    TransactionTypeEnum,
)
from backend.app.api.transactions.models import Transaction
from backend.app.api.transactions.utils import (
    generate_transaction_reference,
    mark_transaction_failed,
)
from backend.app.core.ai.enums import AIReviewStatusEnum
from backend.app.core.ai.models import TransactionRisk
from backend.app.core.ai.service import TransactionAIService
from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.services.transfer_alert import send_transfer_alert_email
from backend.app.core.services.withdrawal_alert import send_withdrawal_alert
from backend.app.core.tasks import generate_statement_task

logger = get_logger()


async def process_deposit(
    amount: Decimal,
    account_id: UUID,
    teller_id: UUID,
    description: str,
    session: AsyncSession,
) -> tuple[Transaction, BankAccount, User]:
    try:
        statement = (
            select(BankAccount, User).join(User).where(BankAccount.id == account_id)
        )
        result = await session.exec(statement)
        account_user = result.first()
        if not account_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
            )

        account, account_owner = account_user

        if not account.account_status == AccountStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account is not active",
            )

        reference = generate_transaction_reference("DEP")

        balance_before = Decimal(str(account.balance))
        balance_after = balance_before + amount

        transaction = Transaction(
            amount=amount,
            description=description,
            reference=reference,
            transaction_type=TransactionTypeEnum.Deposit,
            transaction_category=TransactionCategoryEnum.Credit,
            status=TransactionStatusEnum.Pending,
            balance_before=balance_before,
            balance_after=balance_after,
            receiver_account_id=account_id,
            receiver_id=account_owner.id,
            processed_by=teller_id,
            transaction_metadata={
                "currency": account.currency,
                "account_number": account.account_number,
            },
        )

        teller = await session.get(User, teller_id)
        if teller:
            if transaction.transaction_metadata:
                transaction.transaction_metadata["teller_name"] = teller.full_name
                transaction.transaction_metadata["teller_email"] = teller.email

        account.balance = float(balance_after)

        session.add(transaction)
        session.add(account)
        await session.commit()

        await session.refresh(account)
        await session.refresh(transaction)

        return transaction, account, account_owner

    except HTTPException as http_ex:
        await session.rollback()
        raise http_ex
    except Exception as ex:
        await session.rollback()
        logger.error(f"Failed to process deposit: {ex}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to process deposit"},
        )


async def initiate_transfer(
    *,
    sender_id: UUID,
    sender_account_id: UUID,
    receiver_account_number: str,
    amount: Decimal,
    description: str,
    security_answer: str,
    session: AsyncSession,
) -> Tuple[Transaction, BankAccount, BankAccount, User, User]:
    try:
        self_receiver_result = await session.exec(
            select(BankAccount).where(
                BankAccount.account_number == receiver_account_number,
                BankAccount.user_id == sender_id,
            )
        )
        self_receiver_account = self_receiver_result.first()
        if self_receiver_account:
            raise HTTPException(
                status_code=status.HTTP_406_NOT_ACCEPTABLE,
                detail={
                    "status": "error",
                    "message": "Cannot transfer to your own account",
                },
            )

        sender_result = await session.exec(
            select(BankAccount, User)
            .join(User)
            .where(
                BankAccount.id == sender_account_id,
                BankAccount.user_id == sender_id,
            )
        )
        sender_data = sender_result.first()
        if not sender_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "error", "message": "Sender account not found"},
            )
        sender_account, sender = sender_data

        if sender_account.account_status != AccountStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Sender account is not active"},
            )

        if security_answer != sender.security_question_answer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Security answer does not match"},
            )

        receiver_result = await session.exec(
            select(BankAccount, User)
            .join(User)
            .where(
                BankAccount.account_number == receiver_account_number,
            )
        )
        receiver_data = receiver_result.first()
        if not receiver_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "error", "message": "Receiver account not found"},
            )
        receiver_account, receiver = receiver_data

        if receiver_account.account_status != AccountStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Receiver account is not active"},
            )

        if Decimal(str(sender_account.balance)) < amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Insufficient balance"},
            )

        converted_amount, exchange_rate, conversion_fee = calculate_conversion(
            amount, sender_account.currency, receiver_account.currency
        )

        reference = generate_transaction_reference("TRF")

        transaction = Transaction(
            amount=amount,
            description=description,
            reference=reference,
            transaction_type=TransactionTypeEnum.Transfer,
            transaction_category=TransactionCategoryEnum.Debit,
            status=TransactionStatusEnum.Pending,
            balance_before=Decimal(str(sender_account.balance)),
            balance_after=Decimal(str(sender_account.balance)) - amount,
            sender_account_id=sender_account.id,
            receiver_account_id=receiver_account.id,
            sender_id=sender.id,
            receiver_id=receiver.id,
            transaction_metadata={
                "conversion_rate": str(exchange_rate),
                "conversion_fee": str(conversion_fee),
                "original_amount": str(amount),
                "converted_amount": str(converted_amount),
                "from_currency": sender_account.currency.value,
                "to_currency": receiver_account.currency.value,
            },
        )

        session.add(transaction)
        await session.commit()
        await session.refresh(transaction)

        ai_service = TransactionAIService(session)
        risk_analysis = await ai_service.analyze_transaction(transaction, sender.id)

        if risk_analysis.get("needs_review", False):
            await ai_service.handle_flagged_transaction(transaction, risk_analysis)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "This transaction has been "
                    "flagged as potentially fraudulent. An "
                    "account executive will review the "
                    "transaction, before its either "
                    "approved or rejected",
                    "risk_analysis": {
                        "risk_score": risk_analysis["risk_score"],
                        "risk_factors": risk_analysis["risk_factors"],
                    },
                },
            )

        otp = generate_otp()

        sender.otp = otp
        sender.otp_expiry_time = datetime.now(timezone.utc) + timedelta(
            minutes=settings.OTP_EXPIRATION_MINUTES
        )

        session.add(transaction)
        session.add(sender)

        await session.commit()
        await session.refresh(transaction)
        await session.refresh(sender)

        return transaction, sender_account, receiver_account, sender, receiver

    except HTTPException as http_ex:
        await session.rollback()
        raise http_ex
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to initiate transfer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to initiate transfer"},
        )


async def complete_transfer(
    *, reference: str, otp: str, session: AsyncSession
) -> Tuple[Transaction, BankAccount, BankAccount, User, User]:
    try:
        stmt = select(Transaction).where(
            Transaction.reference == reference,
            Transaction.status == TransactionStatusEnum.Pending,
        )
        result = await session.exec(stmt)
        transaction = result.first()
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "error", "message": "Transaction not found"},
            )

        sender_account = await session.get(BankAccount, transaction.sender_account_id)
        receiver_account = await session.get(
            BankAccount, transaction.receiver_account_id
        )
        sender = await session.get(User, transaction.sender_id)
        receiver = await session.get(User, transaction.receiver_id)

        if not all([sender_account, receiver_account, sender, receiver]):
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.INVALID_ACCOUNT,
                details={
                    "sender_account": bool(sender_account),
                    "receiver_account": bool(receiver_account),
                    "sender": bool(sender),
                    "receiver": bool(receiver),
                },
                session=session,
                error_message="Invalid account details",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Invalid account details",
                    "details": {
                        "sender_account": bool(sender_account),
                        "receiver_account": bool(receiver_account),
                        "sender": bool(sender),
                        "receiver": bool(receiver),
                    },
                },
            )

        if not sender or sender.otp != otp:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.INVALID_OTP,
                details={
                    "provided_otp": otp,
                },
                session=session,
                error_message="Invalid OTP",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP"
            )

        if not sender.otp_expiry_time or sender.otp_expiry_time < datetime.now(
            timezone.utc
        ):
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.OTP_EXPIRED,
                details={
                    "otp_expiry_time": sender.otp_expiry_time.isoformat()
                    if sender.otp_expiry_time
                    else None,
                    "current_time": datetime.now(timezone.utc).isoformat(),
                },
                session=session,
                error_message="OTP expired",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired"
            )

        if sender_account and sender_account.account_status != AccountStatusEnum.Active:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.ACCOUNT_INACTIVE,
                details={
                    "account_status": sender_account.account_status.value,
                },
                session=session,
                error_message="Sender account is inactive",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sender account is inactive",
            )

        if (
            receiver_account
            and receiver_account.account_status != AccountStatusEnum.Active
        ):
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.ACCOUNT_INACTIVE,
                details={
                    "account_status": receiver_account.account_status.value,
                },
                session=session,
                error_message="Receiver account is inactive",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Receiver account is inactive",
            )

        if not sender_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Sender account not found"
            )

        if not receiver_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Receiver account not found",
            )

        if not receiver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Receiver not found",
            )

        if Decimal(str(sender_account.balance)) < transaction.amount:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.INSUFFICIENT_BALANCE,
                details={
                    "sender_balance": sender_account.balance,
                    "amount": transaction.amount,
                },
                session=session,
                error_message="Insufficient balance",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient balance",
            )

        if not transaction.transaction_metadata:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.SYSTEM_ERROR,
                details={"error": "Missing transaction metadata"},
                session=session,
                error_message="Missing transaction metadata",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Missing transaction metadata"},
            )

        if not transaction.transaction_metadata:
            raise ValueError("Missing transaction metadata")

        converted_amount = Decimal(transaction.transaction_metadata["converted_amount"])

        sender_account.balance = float(
            Decimal(str(sender_account.balance)) - transaction.amount
        )
        receiver_account.balance = float(
            Decimal(str(receiver_account.balance)) + converted_amount
        )

        transaction.status = TransactionStatusEnum.Completed
        transaction.completed_at = datetime.now(timezone.utc)

        sender.otp = ""
        sender.otp_expiry_time = None

        session.add(transaction)
        session.add(sender)
        session.add(sender_account)
        session.add(receiver)
        session.add(receiver_account)

        await session.commit()

        await session.refresh(sender_account)
        await session.refresh(receiver_account)
        await session.refresh(transaction)
        await session.refresh(sender)
        await session.refresh(receiver)

        return transaction, sender_account, receiver_account, sender, receiver

    except HTTPException as http_ex:
        await session.rollback()
        raise http_ex
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to complete transfer: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to complete transfer"},
        )


async def process_withdrawal(
    *,
    account_number: str,
    amount: Decimal,
    username: str,
    description: str,
    session: AsyncSession,
) -> Tuple[Transaction, BankAccount, User]:
    try:
        stmt = (
            select(BankAccount, User)
            .join(User)
            .where(
                BankAccount.account_number == account_number, User.username == username
            )
        )

        account_result = await session.exec(stmt)
        account_data = account_result.first()

        if not account_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "error", "message": "Account not found"},
            )

        account, user = account_data

        if account.account_status != AccountStatusEnum.Active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Account is not active"},
            )

        if Decimal(str(account.balance)) < amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Insufficient funds"},
            )

        reference = generate_transaction_reference("WTH")

        balance_before = Decimal(str(account.balance))
        balance_after = balance_before - amount

        transaction = Transaction(
            amount=amount,
            description=description,
            reference=reference,
            transaction_type=TransactionTypeEnum.Withdrawal,
            transaction_category=TransactionCategoryEnum.Debit,
            status=TransactionStatusEnum.Completed,
            balance_before=balance_before,
            balance_after=balance_after,
            sender_account_id=account.id,
            sender_id=user.id,
            completed_at=datetime.now(timezone.utc),
            transaction_metadata={
                "currency": account.currency.value,
                "account_number": account.account_number,
                "withdrawal_method": "cash",
            },
        )

        session.add(transaction)
        await session.commit()
        await session.refresh(transaction)

        ai_service = TransactionAIService(session)
        risk_analysis = await ai_service.analyze_transaction(transaction, user.id)

        if risk_analysis.get("needs_review", False):
            await ai_service.handle_flagged_transaction(transaction, risk_analysis)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "This transaction has been "
                    "flagged as potentially fraudulent. An "
                    "account executive will review the "
                    "transaction, before its either "
                    "approved or rejected",
                    "risk_analysis": {
                        "risk_score": risk_analysis["risk_score"],
                        "risk_factors": risk_analysis["risk_factors"],
                    },
                },
            )

        transaction.status = TransactionStatusEnum.Completed
        transaction.completed_at = datetime.now(timezone.utc)

        account.balance = float(balance_after)

        session.add(account)
        await session.commit()
        await session.refresh(account)

        return transaction, account, user

    except HTTPException as http_ex:
        await session.rollback()
        raise http_ex
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to complete withdrawal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to complete withdrawal"},
        )


async def get_user_transactions(
    user_id: UUID,
    session: AsyncSession,
    offset: int = 0,
    limit: int = 10,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    transaction_type: TransactionTypeEnum | None = None,
    transaction_category: TransactionCategoryEnum | None = None,
    transaction_status: TransactionStatusEnum | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
) -> Tuple[list[Transaction], int]:
    try:
        query = select(BankAccount.id).where(BankAccount.user_id == user_id)
        result = await session.exec(query)
        account_ids = [account_id for account_id in result.all()]

        if not account_ids:
            return [], 0

        base_query = select(Transaction).where(
            or_(
                Transaction.sender_id == user_id,
                Transaction.receiver_id == user_id,
                Transaction.sender_account_id == any_(account_ids),
                Transaction.receiver_account_id == any_(account_ids),
            )
        )

        if start_date:
            base_query = base_query.where(Transaction.created_at >= start_date)
        if end_date:
            base_query = base_query.where(Transaction.created_at <= end_date)
        if transaction_type:
            base_query = base_query.where(
                Transaction.transaction_type == transaction_type
            )
        if transaction_category:
            base_query = base_query.where(
                Transaction.transaction_category == transaction_category
            )
        if transaction_status:
            base_query = base_query.where(Transaction.status == transaction_status)
        if min_amount is not None:
            base_query = base_query.where(Transaction.amount >= min_amount)
        if max_amount is not None:
            base_query = base_query.where(Transaction.amount <= max_amount)

        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await session.exec(count_query)
        total_count = total_result.first() or 0

        page_query = (
            base_query.options(
                selectinload(Transaction.sender),  # type: ignore[arg-type]
                selectinload(Transaction.receiver),  # type: ignore[arg-type]
                selectinload(Transaction.sender_account),  # type: ignore[arg-type]
                selectinload(Transaction.receiver_account),  # type: ignore[arg-type]
            )
            .order_by(desc(Transaction.created_at))
            .offset(offset)
            .limit(limit)
        )
        transactions = await session.exec(page_query)
        transactions_list = list(transactions.all())

        for transaction in transactions_list:
            if not transaction.transaction_metadata:
                transaction.transaction_metadata = {}

            # user is sender
            if transaction.sender_id == user_id:
                if transaction.receiver:
                    transaction.transaction_metadata["counterparty_name"] = (
                        transaction.receiver.full_name
                    )
                if transaction.receiver_account:
                    transaction.transaction_metadata["counterparty_account"] = (
                        transaction.receiver_account.account_number
                    )
            # user is receiver
            else:
                if transaction.sender:
                    transaction.transaction_metadata["counterparty_name"] = (
                        transaction.sender.full_name
                    )
                if transaction.sender_account:
                    transaction.transaction_metadata["counterparty_account"] = (
                        transaction.sender_account.account_number
                    )

        return transactions_list, total_count

    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to get user transactions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to get user transactions"},
        )


async def get_user_statement_data(
    user_id: UUID,
    start_date: datetime,
    end_date: datetime,
    session: AsyncSession,
) -> Tuple[dict[str, Any], list[Transaction]]:
    try:
        user = await session.get(User, user_id)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "error", "message": "User not found"},
            )

        full_name = f"{user.first_name} {user.middle_name if user.middle_name else ''} {user.last_name}".title().strip()

        user_info = {
            "username": user.username,
            "email": user.email,
            "full_name": full_name,
        }

        txn_statement = (
            select(Transaction)
            .where(
                (Transaction.sender_id == user_id)
                | (Transaction.receiver_id == user_id),
                Transaction.created_at >= start_date,
                Transaction.created_at <= end_date,
            )
            .order_by(desc(Transaction.created_at))
        )
        txn_result = await session.exec(txn_statement)
        transactions = txn_result.all()

        return user_info, list(transactions)

    except Exception as ex:
        await session.rollback()
        logger.error(f"Failed to get user statement data: {ex}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to get user statement data"},
        )


async def prepare_statement_data(
    user_id: UUID,
    start_date: datetime,
    end_date: datetime,
    session: AsyncSession,
    account_number: str | None = None,
) -> dict:
    try:
        user = await session.get(User, user_id)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "error", "message": "User not found"},
            )

        if account_number:
            accounts_query = select(BankAccount).where(
                BankAccount.account_number == account_number,
                BankAccount.user_id == user_id,
            )
            account_result = await session.exec(accounts_query)
            account = account_result.first()

            if not account:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "error",
                        "message": "Account not found or does not belong to the user",
                    },
                )

            accounts = [account]

        else:
            accounts_query = select(BankAccount).where(BankAccount.user_id == user_id)
            accounts_result = await session.exec(accounts_query)
            accounts = accounts_result.all()

        account_details = []

        for acc in accounts:
            account_details.append(
                {
                    "account_number": acc.account_number,
                    "account_name": acc.account_name,
                    "account_type": acc.account_type,
                    "currency": acc.currency,
                    "balance": str(acc.balance),
                }
            )

        user_data = {
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": f"{user.first_name} {user.middle_name if user.middle_name else ''} {user.last_name}".title().strip(),
            "accounts": account_details,
        }

        account_ids = [acc.id for acc in accounts]

        transactions_query = (
            select(Transaction)
            .where(
                or_(
                    Transaction.sender_account_id == any_(account_ids),
                    Transaction.receiver_account_id == any_(account_ids),
                ),
                Transaction.created_at >= start_date,
                Transaction.created_at <= end_date,
                Transaction.status == TransactionStatusEnum.Completed,
            )
            .order_by(desc(Transaction.created_at))
        )

        result = await session.exec(transactions_query)
        transactions = result.all()

        transactions_data = []

        for txn in transactions:
            sender_account = (
                await session.get(BankAccount, txn.sender_account_id)
                if txn.sender_account_id
                else None
            )
            receiver_account = (
                await session.get(BankAccount, txn.receiver_account_id)
                if txn.receiver_account_id
                else None
            )

            transactions_data.append(
                {
                    "reference": txn.reference,
                    "amount": str(txn.amount),
                    "description": txn.description,
                    "created_at": txn.created_at.strftime("%Y-%m-%d"),
                    "transaction_type": txn.transaction_type.value,
                    "transaction_category": txn.transaction_category.value,
                    "balance_after": str(txn.balance_after),
                    "sender_account": (
                        sender_account.account_number if sender_account else None
                    ),
                    "receiver_account": (
                        receiver_account.account_number if receiver_account else None
                    ),
                    "metadata": txn.transaction_metadata,
                }
            )

        return {
            "user": user_data,
            "transactions": transactions_data,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "is_single_account": bool(account_number),
        }

    except Exception as ex:
        logger.error(f"Failed to prepare statement data: {ex}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to prepare statement data"},
        )


async def generate_user_statement(
    user_id: UUID,
    start_date: datetime,
    end_date: datetime,
    session: AsyncSession,
    account_number: str | None = None,
) -> dict:
    try:
        statement_data = await prepare_statement_data(
            user_id, start_date, end_date, session, account_number
        )

        statement_id = str(uuid.uuid4())

        task = generate_statement_task.delay(statement_id, statement_data)  # type: ignore

        return {
            "status": "pending",
            "message": "Statement generation task has been started",
            "statement_id": statement_id,
            "task_id": task.id,
        }
    except ValueError as ve:
        logger.error(f"Failed to prepare statement data: {ve}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": "Invalid input"},
        )
    except Exception as ex:
        logger.error(f"Failed to generate user statement: {ex}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "error", "message": "Failed to generate user statement"},
        )


async def review_flagged_transactions(
    transaction_id: UUID,
    reviewer_id: UUID,
    is_fraud: bool,
    approve_transaction: bool,
    session: AsyncSession,
    notes: str | None = None,
) -> dict:
    try:
        query = (
            select(Transaction, TransactionRisk)
            .join(TransactionRisk)
            .where(TransactionRisk.transaction_id == transaction_id)
        )
        result = await session.exec(query)
        transaction_data = result.first()

        if transaction_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "error", "message": "Transaction not found"},
            )

        transaction, transaction_risk = transaction_data

        if transaction.ai_review_status != AIReviewStatusEnum.FLAGGED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "error",
                    "message": "Transaction is not marked as flagged",
                },
            )

        if is_fraud:
            transaction.ai_review_status = AIReviewStatusEnum.CONFIRMED_FRAUD
            transaction_risk.is_confirmed_fraud = True
            transaction_risk.reviewed_by = reviewer_id
            transaction.status = TransactionStatusEnum.Failed
        else:
            transaction.ai_review_status = AIReviewStatusEnum.CLEARED

        if approve_transaction:
            if transaction.transaction_type == TransactionTypeEnum.Transfer:
                await _complete_approved_transfer(transaction, session)
            elif transaction.transaction_type == TransactionTypeEnum.Withdrawal:
                await _complete_approved_withdrawal(transaction, session)

        if not transaction.transaction_metadata:
            transaction.transaction_metadata = {}

        transaction.transaction_metadata["fraud_review"] = {
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": reviewer_id,
            "is_fraud": is_fraud,
            "notes": notes,
        }

        session.add(transaction)
        await session.commit()
        await session.refresh(transaction)

        return {
            "status": "success",
            "message": "Transaction reviewed successfully",
            "transaction": transaction,
            "is_fraud": is_fraud,
            "risk_score": transaction_risk.risk_score,
            "review_status": transaction.ai_review_status,
        }

    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to review flagged transaction: {ex}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to review flagged transaction",
            },
        )


async def _complete_approved_transfer(transaction: Transaction, session: AsyncSession):
    try:
        sender = await session.get(User, transaction.sender_id)

        receiver = await session.get(User, transaction.receiver_id)

        sender_account = await session.get(BankAccount, transaction.sender_account_id)

        receiver_account = await session.get(
            BankAccount, transaction.receiver_account_id
        )

        if not sender:
            raise ValueError("Sender not found")
        if not receiver:
            raise ValueError("Receiver not found")
        if not sender_account:
            raise ValueError("Sender account not found")
        if not receiver_account:
            raise ValueError("Receiver account not found")

        if not transaction.transaction_metadata:
            raise ValueError("Transaction metadata is missing")

        converted_amount_str = transaction.transaction_metadata.get("converted_amount")
        if not converted_amount_str:
            raise ValueError("Converted amount is missing in transaction metadata")

        try:
            converted_amount = Decimal(converted_amount_str)
        except (TypeError, ValueError):
            raise ValueError("Converted amount is not a valid decimal")

        current_sender_balance = Decimal(str(sender_account.balance))

        if current_sender_balance < transaction.amount:
            raise ValueError("Insufficient balance")

        try:
            sender_account.balance = float(current_sender_balance - transaction.amount)
            receiver_account.balance = float(
                Decimal(str(receiver_account.balance)) + converted_amount
            )

            transaction.status = TransactionStatusEnum.Completed
            transaction.completed_at = datetime.now(timezone.utc)

            session.add(sender_account)
            session.add(receiver_account)
            session.add(transaction)

            await session.commit()

            await session.refresh(transaction)
            await session.refresh(sender_account)
            await session.refresh(receiver_account)

            try:
                await send_transfer_alert_email(
                    sender_email=sender.email,
                    receiver_email=receiver.email,
                    sender_name=sender.full_name,
                    receiver_name=receiver.full_name,
                    sender_account_number=sender_account.account_number or "Unknown",
                    receiver_account_number=receiver_account.account_number
                    or "Unknown",
                    amount=transaction.amount,
                    converted_amount=converted_amount,
                    sender_currency=sender_account.currency,
                    receiver_currency=receiver_account.currency,
                    exchange_rate=Decimal(
                        transaction.transaction_metadata.get("conversion_rate", "1"),
                    ),
                    conversion_fee=Decimal(
                        transaction.transaction_metadata.get("conversion_fee", "0"),
                    ),
                    description=transaction.description,
                    reference=transaction.reference,
                    transaction_date=transaction.completed_at or transaction.created_at,
                    sender_balance=Decimal(str(sender_account.balance)),
                    receiver_balance=Decimal(str(receiver_account.balance)),
                )
                logger.info(
                    f"Successfully sent transfer approval notification for transaction {transaction.reference}"
                )
            except Exception as e:
                logger.error(f"Failed to send transfer approval notification: {e}")

        except Exception as e:
            await session.rollback()
            raise ValueError(f"Failed to process transfer: {str(e)}")

    except ValueError as e:
        await session.rollback()
        logger.error(f"Validation error in _complete_approved_transfer: {e}")

        transaction.status = TransactionStatusEnum.Failed
        transaction.transaction_metadata = {
            **(transaction.transaction_metadata or {}),
            "failure_reason": str(e),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        session.add(transaction)
        await session.commit()
        raise

    except Exception as ex:
        logger.error(f"Failed to complete approved transfer: {ex}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to complete approved transfer",
            },
        )


async def _complete_approved_withdrawal(
    transaction: Transaction, session: AsyncSession
):
    try:
        user = await session.get(User, transaction.sender_id)
        account = await session.get(BankAccount, transaction.sender_id)

        if not user:
            raise ValueError("User not found")
        if not account:
            raise ValueError("Bank account not found")

        if Decimal(str(account.balance)) < transaction.amount:
            raise ValueError("Insufficient balance for withdrawal")

        try:
            account.balance = float(Decimal(str(account.balance)) - transaction.amount)

            transaction.status = TransactionStatusEnum.Completed
            transaction.completed_at = datetime.now(timezone.utc)

            session.add(account)
            session.add(transaction)

            await session.commit()

            await session.refresh(transaction)
            await session.refresh(account)

            try:
                await send_withdrawal_alert(
                    email=user.email,
                    full_name=user.full_name,
                    amount=transaction.amount,
                    account_name=account.account_name,
                    account_number=account.account_number or "Unknown",
                    currency=account.currency.value,
                    transaction_date=transaction.completed_at or transaction.created_at,
                    reference=transaction.reference,
                    balance=Decimal(str(account.balance)),
                    description=transaction.description,
                )
                logger.info(
                    f"Successfully sent withdrawal approval notification for transaction {transaction.reference}"
                )
            except Exception as e:
                logger.error(f"Failed to send withdrawal approval notification: {e}")

        except Exception as e:
            await session.rollback()
            raise ValueError(f"Failed to complete approved withdrawal: {str(e)}")
    except ValueError as e:
        await session.rollback()
        logger.error(f"Validation error in _complete_approved_withdrawal: {e}")

        transaction.status = TransactionStatusEnum.Failed
        transaction.transaction_metadata = {
            **(transaction.transaction_metadata or {}),
            "failure_reason": str(e),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        session.add(transaction)
        await session.commit()
        raise

    except Exception as e:
        logger.error(f"Failed to complete approved withdrawal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to complete approved withdrawal",
            },
        )


async def get_user_risk_history(
    user_id: uuid.UUID,
    session: AsyncSession,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_risk_score: float | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[dict], int]:
    try:
        base_query = (
            select(Transaction, TransactionRisk)
            .join(TransactionRisk)
            .where(
                Transaction.sender_id == user_id,
            )
        )

        if start_date:
            base_query = base_query.where(Transaction.created_at >= start_date)
        if end_date:
            base_query = base_query.where(Transaction.created_at <= end_date)
        if min_risk_score is not None:
            base_query = base_query.where(TransactionRisk.risk_score >= min_risk_score)

        base_query = base_query.order_by(
            desc(Transaction.created_at), desc(TransactionRisk.risk_score)
        )

        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await session.exec(count_query)
        total_count = total_result.first() or 0

        paginated_query = base_query.offset(skip).limit(limit)
        result = await session.exec(paginated_query)
        transactions = result.all()

        history = []

        for transaction, risk_score in transactions:
            history.append(
                {
                    "transaction_id": str(transaction.id),
                    "reference": transaction.reference,
                    "amount": str(transaction.amount),
                    "created_at": transaction.created_at,
                    "risk_score": risk_score.risk_score,
                    "risk_factors": risk_score.risk_factors,
                    "review_status": transaction.ai_review_status,
                    "is_confirmed_fraud": risk_score.is_confirmed_fraud,
                    "reviewed_by": (
                        str(risk_score.reviewed_by) if risk_score.reviewed_by else None
                    ),
                    "review_details": (
                        transaction.transaction_metadata.get("fraud_review")
                        if transaction.transaction_metadata
                        else None
                    ),
                }
            )
        return history, total_count

    except Exception as e:
        logger.error(f"Failed to get user risk history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to get user risk history",
            },
        )
