import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel
from typing_extensions import Annotated

from backend.app.api.transactions.enums import (
    TransactionCategoryEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)


class TransactionBaseSchema(SQLModel):
    amount: Annotated[Decimal, Field(decimal_places=2, ge=0)]
    description: str = Field(max_length=250)
    reference: str = Field(unique=True, index=True)
    transaction_type: TransactionTypeEnum
    transaction_category: TransactionCategoryEnum
    status: TransactionStatusEnum = Field(default=TransactionStatusEnum.Pending)
    balance_before: Annotated[Decimal, Field(decimal_places=2)]
    balance_after: Annotated[Decimal, Field(decimal_places=2)]

    transaction_metadata: dict | None = Field(default=None, sa_column=Column(JSONB))
    failed_reason: str | None = Field(default=None)


class TransactionCreateSchema(TransactionBaseSchema):
    pass


class TransactionReadSchema(TransactionBaseSchema):
    id: uuid.UUID

    created_at: datetime = Field(
        sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False)
    )

    completed_at: datetime | None = Field(
        default=None, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True)
    )


class TransactionUpdateSchema(TransactionBaseSchema):
    pass


class TransferRequestSchema(SQLModel):
    sender_account_id: uuid.UUID
    receiver_account_number: str = Field(min_length=16, max_length=16)
    amount: Decimal = Field(ge=0, decimal_places=2)
    security_answer: str = Field(max_length=30)
    description: str = Field(max_length=250)


class DepositRequestSchema(SQLModel):
    account_id: uuid.UUID
    amount: Decimal = Field(ge=0, decimal_places=2)
    description: str = Field(max_length=250)


class TransferOTPVerificationSchema(SQLModel):
    transfer_reference: str
    otp: str = Field(min_length=6, max_length=6)


class TransferResponseSchema(SQLModel):
    status: str
    message: str
    data: dict | None = None


class CurrencyConversionSchema(SQLModel):
    amount: Decimal
    from_currency: str
    to_currency: str
    exchange_rate: Decimal
    original_amount: Decimal
    converted_amount: Decimal
    conversion_fee: Decimal = Field(default=Decimal("0.00"))


class WithdrawalRequestSchema(SQLModel):
    account_number: str = Field(min_length=16, max_length=16)
    amount: Decimal = Field(ge=0, decimal_places=2)
    username: str = Field(min_length=1, max_length=12)
    description: str = Field(max_length=250)


class TransactionHistoryResponseSchema(SQLModel):
    id: uuid.UUID
    reference: str
    amount: Decimal
    description: str
    transaction_type: TransactionTypeEnum
    transaction_category: TransactionCategoryEnum
    transaction_status: TransactionStatusEnum
    created_at: datetime
    completed_at: datetime | None = None
    balance_after: Decimal
    currency: str | None = None
    converted_amount: str | None = None
    from_currency: str | None = None
    to_currency: str | None = None
    counterparty_name: str | None = None
    counterparty_account: str | None = None


class PaginatedTransactionResponseSchema(SQLModel):
    total: int
    offset: int
    limit: int
    transactions: list[TransactionHistoryResponseSchema]


class TransactionFilterParamsSchema(SQLModel):
    model_config = {"extra": "forbid"}  # type: ignore[assignment]

    limit: int = Field(
        default=10, ge=1, le=100, description="Maximum number of transactions to return"
    )
    offset: int = Field(default=0, ge=0, description="Number of transactions to skip")
    start_date: datetime | None = Field(
        default=None,
        description="Filter transactions from this date (inclusive)",
        schema_extra={"examples": ["2025-01-01T00:00:00Z"]},
    )
    end_date: datetime | None = Field(
        default=None,
        description="Filter transactions up to this date (inclusive)",
        schema_extra={"examples": ["2025-12-31T23:59:59Z"]},
    )
    transaction_type: TransactionTypeEnum | None = Field(
        default=None,
        description="Filter transactions by type",
    )
    transaction_category: TransactionCategoryEnum | None = Field(
        default=None,
        description="Filter transactions by category",
    )
    status: TransactionStatusEnum | None = Field(
        default=None,
        description="Filter transactions by status",
    )
    min_amount: Decimal | None = Field(
        default=None,
        ge=0,
        description="Filter transactions by minimum amount",
    )
    max_amount: Decimal | None = Field(
        default=None,
        ge=0,
        description="Filter transactions by maximum amount",
    )


class StatementRequestSchema(SQLModel):
    start_date: datetime
    end_date: datetime
    account_number: str | None = Field(
        default=None,
        min_length=16,
        max_length=16,
    )


class StatementResponseSchema(SQLModel):
    status: str
    message: str
    task_id: str | None = None
    statement_id: str | None = None
    generated_at: datetime | None = None
    expires_at: datetime | None = None
