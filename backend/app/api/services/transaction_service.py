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
from backend.app.core.config import settings
from backend.app.core.logging import get_logger
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

        converted_amount_str = transaction.transaction_metadata.get("converted_amount")
        if not converted_amount_str:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.SYSTEM_ERROR,
                details={"error": "Missing converted amount"},
                session=session,
                error_message="Missing converted amount",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Missing converted amount"},
            )

        try:
            converted_amount = Decimal(converted_amount_str)
        except (TypeError, ValueError):
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.SYSTEM_ERROR,
                details={"error": "Invalid converted amount"},
                session=session,
                error_message="Invalid converted amount",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"status": "error", "message": "Invalid converted amount"},
            )

        sender_account.balance = float(
            Decimal(str(sender_account.balance)) - converted_amount
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

        account.balance = float(balance_after)

        session.add(transaction)
        session.add(account)
        await session.commit()
        await session.refresh(transaction)
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
