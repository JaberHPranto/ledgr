from datetime import date, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from backend.app.api.virtual_card.enums import (
    CardBlockReasonEnum,
    VirtualCardBrandEnum,
    VirtualCardCurrencyEnum,
    VirtualCardStatusEnum,
    VirtualCardTypeEnum,
)


class VirtualCardBaseSchema(SQLModel):
    card_type: VirtualCardTypeEnum
    card_brand: VirtualCardBrandEnum = Field(default=VirtualCardBrandEnum.Visa)
    currency: VirtualCardCurrencyEnum = Field(default=VirtualCardCurrencyEnum.USD)
    card_status: VirtualCardStatusEnum = Field(default=VirtualCardStatusEnum.Pending)
    daily_limit: float = Field(gt=0)
    monthly_limit: float = Field(gt=0)
    name_on_card: str = Field(max_length=50)
    expiry_date: date | None = Field(default=None)
    is_active: bool = Field(default=True)
    is_physical_card_requested: bool = Field(default=False)
    block_reason: CardBlockReasonEnum | None = Field(default=None)
    block_reason_description: str | None = Field(default=None)
    card_number: str | None = Field(default=None)
    card_metadata: dict | None = Field(default=None)


class VirtualCardCreateSchema(VirtualCardBaseSchema):
    bank_account_id: UUID


class VirtualCardReadSchema(VirtualCardBaseSchema):
    id: UUID
    bank_account_id: UUID
    last_four_digits: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class VirtualCardUpdateSchema(SQLModel):
    daily_limit: float | None = Field(default=None, gt=0)
    monthly_limit: float | None = Field(default=None, gt=0)
    is_active: bool | None = Field(default=None)


class VirtualCardBlockSchema(SQLModel):
    block_reason: CardBlockReasonEnum = Field()
    block_reason_description: str = Field()
    blocked_at: datetime = Field()
    blocked_by: UUID = Field()


class VirtualCardStatusSchema(VirtualCardBaseSchema):
    card_status: VirtualCardStatusEnum = Field()
    available_balance: float
    daily_limit: float = Field()
    monthly_limit: float = Field()
    total_spend_today: float
    total_spend_this_month: float
    last_transaction_date: datetime | None = None
    last_transaction_amount: float | None = None


class PhysicalCardRequestSchema(SQLModel):
    delivery_address: str = Field(max_length=200)
    city: str = Field(max_length=100)
    country: str = Field(max_length=100)
    postal_code: str = Field(max_length=20)


class CardTopUpSchema(SQLModel):
    account_number: str = Field(min_length=16, max_length=16)
    amount: float = Field(gt=0)
    description: str = Field(max_length=250)


class CardTopUpResponseSchema(SQLModel):
    status: str
    message: str
    data: dict | None = None


class CardDeleteResponseSchema(SQLModel):
    status: str
    message: str
    deleted_at: datetime


class CardBlockSchema(SQLModel):
    block_reason: CardBlockReasonEnum
    block_reason_description: str = Field(max_length=250)
