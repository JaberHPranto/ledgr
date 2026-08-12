from datetime import date
from enum import Enum

from pydantic_extra_types.country import CountryShortName
from pydantic_extra_types.phone_numbers import PhoneNumber
from sqlmodel import Field, SQLModel


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
