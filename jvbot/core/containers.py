from dataclasses import dataclass, field, _MISSING_TYPE, fields
from abc import ABC
from typing import Type, List, Callable, Dict, Any, Optional, Union


@dataclass
class BaseConstantsConfig(ABC):
    def __post_init__(self):
        for field in fields(self):
            # If there is a default value and the value of the field is missin, then we can assign a value
            if not isinstance(field.default, _MISSING_TYPE) and getattr(self, field.name) is None:
                setattr(self, field.name, field.default)

@dataclass
class ProtocolMetadataConfig(BaseConstantsConfig):
    name: str
    author: Union[str, List[str]]
    version: str
    description: str
    references: List[str] # DOIs
    protocol_class: Type[Any] # execute some measurement protocol
    formatter_class: Type[Any] # save data, plot data
    tags: List[str] = field(default_factory = list)
    source_code: str = ""
    additional_notes: Optional[str] = None

    def __str__(self):
        """Readable terminal output."""
        refs = "\n\t- ".join(self.references)
        output = f"=== Protocol: {self.name} (v{self.version}) ===\n"
        output += f"Author(s): {self.author}\n" 
        output += f"Description: {self.description}\n"
        output += f"Source Code: {self.source_code}\n"
        output += f"References: \n\t - {refs}\n"
        output += f"Tags: {', '.join(self.tags)}\n"
        output += 20*"="