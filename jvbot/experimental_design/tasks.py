"""This document contains the class containers representative of a unique measurement protocol."""
from dataclasses import dataclass
from abc import ABC, abstractmethod
from ..hardware.base_config import BaseConstantsConfig

@dataclass
class MeasurementConfig(BaseConstantsConfig):
    applied_load: str = "Voltage" # "Voltage", "Current", "Resistance"
    source_start: float = 0
    source_end: float = 1.2
    N_datapoints: 100


class BaseJVProtocol(ABC):
    def __init__(self, measurement_configuration: MeasurementConfig):
        self._measurement_configuration = measurement_configuration
    
    @property
    def measureconfig(self):
        return self._measurement_configuration
    
    @abstractmethod
    def get_ready_to_measure(self):
        """Depending on the JVProtocol, prepare the source measure unit to get up and go."""
        pass

    # @abstractmethod
    # def 



