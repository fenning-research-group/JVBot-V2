"""The BaseConfig exists primarily for type checking across hardware constant dataclass implementations."""
from dataclasses import dataclass, fields, _MISSING_TYPE
from abc import ABC

@dataclass
class BaseConstantsConfig(ABC):
    def __post_init__(self):
        for field in fields(self):
            # If there is a default value and the value of the field is missin, then we can assign a value
            if not isinstance(field.default, _MISSING_TYPE) and getattr(self, field.name) is None:
                setattr(self, field.name, field.default)