from enum import Enum

from fastapi.exceptions import HTTPException
from pydantic import field_validator
from sqlmodel import Field, SQLModel
from sqlmodel.main import EmailStr


class SecurityQuestionSchema(str, Enum):
    MOTHER_MAIDEN_NAME = "mother_maiden_name"
    CHILDHOOD_FRIEND = "childhood_friend"
    FAVORITE_COLOR = "favorite_color"
    BIRTH_CITY = "birth_city"

    @classmethod
    def get_description(cls, value: "SecurityQuestionSchema") -> str:
        description = {
            cls.MOTHER_MAIDEN_NAME: "What is the name of your mother?",
            cls.CHILDHOOD_FRIEND: "What is the name of your childhood friend?",
            cls.FAVORITE_COLOR: "What is your favorite color?",
            cls.BIRTH_CITY: "What is the name of the city you were born in?",
        }

        return description.get(value, "Unknown security question")


class AccountStatusSchema(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    PENDING = "pending"


class RoleChoicesSchema(str, Enum):
    CUSTOMER = "customer"
    ACCOUNT_EXECUTIVE = "account_executive"
    BRANCH_MANAGER = "branch_manager"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"
    TELLER = "teller"


class BaseUserSchema(SQLModel):
    username: str | None = Field(default=None, unique=True, max_length=12)
    email: EmailStr = Field(index=True, max_length=255)
    first_name: str = Field(max_length=30)
    middle_name: str | None = Field(max_length=30, default=None)
    last_name: str = Field(max_length=30)
    id_no: int = Field(unique=True, gt=0)
    is_active: bool = Field(default=False)
    is_superuser: bool = Field(default=False)
    security_question: SecurityQuestionSchema = Field(max_length=30)
    security_question_answer: str = Field(max_length=30)
    account_status: AccountStatusSchema = Field(default=AccountStatusSchema.INACTIVE)
    role: RoleChoicesSchema = Field(default=RoleChoicesSchema.CUSTOMER)


class UserCreateSchema(BaseUserSchema):
    password: str = Field(min_length=6, max_length=20)
    confirm_password: str = Field(min_length=6, max_length=20)

    @field_validator("confirm_password")
    def check_passwords_match(cls, field_value, values):
        if "password" in values and "confirm_password" in values:
            if field_value != values["password"]:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "status": "error",
                        "message": "Passwords do not match",
                        "action": "Please ensure that the passwords you entered match",
                    },
                )
        return field_value
