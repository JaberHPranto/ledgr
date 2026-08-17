from enum import Enum


class RelationshipTypeEnum(str, Enum):
    SPOUSE = "Spouse"
    SIBLING = "Sibling"
    PARENT = "Parent"
    CHILD = "Child"
    OTHER = "Other"
