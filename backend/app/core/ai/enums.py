from enum import Enum


class AIReviewStatusEnum(Enum):
    PENDING = "pending"
    FLAGGED = "flagged"
    CLEARED = "cleared"
    CONFIRMED_FRAUD = "confirmed_fraud"
