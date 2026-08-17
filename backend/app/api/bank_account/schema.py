import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from backend.app.api.bank_account.enums import (
    AccountCurrencyEnum,
    AccountStatusEnum,
    AccountTypeEnum,
)


class BankAccountBaseSchema(SQLModel):
    account_name: str
    account_number: str | None = Field(default=None, unique=True, index=True)
    account_type: AccountTypeEnum
    account_status: AccountStatusEnum = Field(default=AccountStatusEnum.Pending)
    currency: AccountCurrencyEnum
    balance: float = Field(default=0.0)
    is_primary: bool = Field(default=False)
    kyc_submitted: bool = Field(default=False)
    kyc_verified: bool = Field(default=False)
    kyc_verified_by: uuid.UUID | None = Field(default=None)
    interest_rate: float = Field(default=0.0)


class BankAccountCreateSchema(BankAccountBaseSchema):
    account_number: str | None = Field(default=None)


class BankAccountReadSchema(BankAccountBaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    account_number: str | None = None
    created_at: datetime
    updated_at: datetime


class BankAccountUpdateSchema(SQLModel):
    account_name: str | None = None
    is_primary: bool | None = None
    account_status: AccountStatusEnum | None = None
