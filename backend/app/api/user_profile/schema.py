from datetime import date
from enum import Enum

from pydantic import ConfigDict, ValidationInfo, field_validator
from pydantic_extra_types.country import CountryShortName
from pydantic_extra_types.phone_numbers import PhoneNumber
from sqlmodel import Field, SQLModel

from backend.app.api.auth.schema import RoleChoicesSchema
from backend.app.api.user_profile.utils import validate_id_dates


class SalutationEnum(str, Enum):
    Mr = "Mr"
    Mrs = "Mrs"
    Miss = "Miss"


class GenderEnum(str, Enum):
    Male = "Male"
    Female = "Female"
    Other = "Other"


class MaritalStatusEnum(str, Enum):
    Married = "Married"
    Divorced = "Divorced"
    Single = "Single"
    Widowed = "Widowed"


class IdentificationTypeEnum(str, Enum):
    Passport = "Passport"
    Drivers_License = "Drivers_License"
    National_ID = "National_ID"


class EmploymentStatusEnum(str, Enum):
    Employed = "Employed"
    Unemployed = "Unemployed"
    Self_Employed = "Self_Employed"
    Student = "Student"
    Retired = "Retired"


class ImageTypeEnum(str, Enum):
    PROFILE_PHOTO = "profile_photo"
    ID_PHOTO = "id_photo"
    SIGNATURE_PHOTO = "signature_photo"


class ProfileBaseSchema(SQLModel):
    title: SalutationEnum
    gender: GenderEnum
    date_of_birth: date
    country_of_birth: CountryShortName
    place_of_birth: str
    marital_status: MaritalStatusEnum
    means_of_identification: IdentificationTypeEnum
    id_issue_date: date
    id_expiry_date: date
    passport_number: str
    nationality: str
    phone_number: PhoneNumber
    address: str
    city: str
    country: str
    employment_status: EmploymentStatusEnum
    employer_name: str
    employer_address: str
    employer_city: str
    employer_country: CountryShortName
    annual_income: float
    date_of_employment: date
    profile_photo_url: str | None = Field(default=None)
    id_photo_url: str | None = Field(default=None)
    signature_photo_url: str | None = Field(default=None)


class ProfileCreateSchema(ProfileBaseSchema):
    @field_validator("id_issue_date")
    def validate_id_issue_date(cls, value, info: ValidationInfo):
        if "id_issue_date" in info.data:
            validate_id_dates(info.data["id_issue_date"], value)
        return value


class ProfileUpdateSchema(SQLModel):
    title: SalutationEnum | None = None
    gender: GenderEnum | None = None
    date_of_birth: date | None = None
    country_of_birth: CountryShortName | None = None
    place_of_birth: str | None = None
    marital_status: MaritalStatusEnum | None = None
    means_of_identification: IdentificationTypeEnum | None = None
    id_issue_date: date | None = None
    id_expiry_date: date | None = None
    passport_number: str | None = None
    nationality: str | None = None
    phone_number: PhoneNumber | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    employment_status: EmploymentStatusEnum | None = None
    employer_name: str | None = None
    employer_address: str | None = None
    employer_city: str | None = None
    employer_country: CountryShortName | None = None
    annual_income: float | None = None
    date_of_employment: date | None = None

    @field_validator("id_expiry_date")
    def validate_id_dates(cls, v: date | None, values) -> date | None:
        if v is not None and "id_issue_date" in values.data:
            validate_id_dates(values.data["id_issue_date"], v)
        return v


class ProfileResponseSchema(SQLModel):
    username: str
    first_name: str
    middle_name: str | None
    last_name: str
    email: str
    id_no: int
    role: RoleChoicesSchema
    profile: ProfileBaseSchema | None


class PaginatedProfileResponseSchema(SQLModel):
    profiles: list[ProfileResponseSchema]
    total: int
    offset: int
    limit: int
