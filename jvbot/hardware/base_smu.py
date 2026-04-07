from pymeasure.instruments.keithley import Keithley2400
import numpy
import matplotlib.pyplot as plt
import pandas
import time
import csv
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields, _MISSING_TYPE
from typing import Dict, List, Union, Tuple


@dataclass
class KeithleyConfig:
    """dataclass for storing the base properties used for legacy keithley operation
    
    Attributes:
    -----------
    area : float, optional
        Active area of a cell, in cm^2, defaults to the 10-mm 1-pixel 
        device architecture active area of 0.048
    address : str, optional
        the networking address of the keithley, by default "GPIB0::22::INSTR"
    """
    area: float = 0.048
    wires: int = 4
    compliance_current: float = 1.05 # A
    compliance_voltage: float = 2 # V
    buffer_points: int = 2
    _scan_speeds: Dict[str, List[float]] = field(default_factory = dict)
    _current_nplc: int = 1 # nplc == number of power line cycles
    _voltage_nplc: int = 1
    _resistance_nplc: int = 1
    _source_delay: float = 0.001 # seconds
    _address: str = "GPIB0::22::INSTR"
    
    def __post_init__(self):
        for field in fields(self):
            # If there is a default and the value of the field is missing, then we can assign a value
            if not isinstance(field.default, _MISSING_TYPE) and getattr(self, field.name) is None:
                setattr(self, field.name, field.default)

class BaseControlKeithley(ABC):
    """Template for a class to control a keithley with JVBot.
    """

    def __init__(self, config: KeithleyConfig = KeithleyConfig()):
        """Initialize Keithley 2400 class SMUs
        """
        self._config = config
        self.__previewFigure = None
        self.__previewAxes = None
        self.preview_figs = {}

    @property
    def config(self) -> KeithleyConfig:
        return self._config
    
    def help(self):
        """Prints useful information to terminal.
        """
        output = "Variables\n"
        output += f"active area = {self.config.area}\n"
        output += f"probe wires = {self.config.wires}\n"
        output += f"compliance_current = {self.config.compliance_current}\n"
        output += f"compliance_voltage = {self.config.compliance_voltage}\n"
        print(output)
    
    def connect(self, keithley_address: str):
        """Setup communication with the Keithley."""
        self.keithley = Keithley2400(keithley_address)
        self.keithley.reset()
        self.keithley.use_front_terminals()
        self.keithley.apply_voltage()
        self.keithley.wires = self.config.wires
        self.keithley.compliance_current = self.config.compliance_current
        self.keithley.compliance_voltage = self.config.compliance_voltage
        self.keithley.buffer_points = self.config.buffer_points
        self.keithley.source_voltage = 0

    def disconnect(self):
        """Disconnect from the GPIB interface."""
        self.keithley.shutdown()

    def _source_voltage_measure_current(self):
        """
            Sets up sourcing voltage and measuring current.
        """
        self.keithley.apply_voltage()
        self.keithley.measure_current()
        self.keithley.compliance_current = self.config.compliance_current
        self.keithley.source_voltage = 0
    
    def _source_current_measure_voltage(self):
        """
            Sets up sourcig current and measuring voltage.
        """
        self.keithley.apply_current()
        self.keithley.measure_voltage()
        self.keithley.compliance_voltage = self.config.compliance_voltage

    def jsc(self, printed: bool = True) -> float:
        """Conducts a short circuit current density measurement.
        Args:
        -----
            printed (boolean = True): boolean to determine if jsc is printed
        Returns:
        --------
            float: Short Circuit Current Density (mA/cm2)
        """
        self._source_voltage_measure_current()
        self.keithley.source_voltage = 0
        self.keithley.enable_source()
        isc = -self._measure()[1]
        jsc_val = isc*1000/self.config.area
        self.keithley.disable_source()
        if printed:
            print(f"Isc: {isc:.3f} A, Jsc: {jsc_val:.2f} mA/cm2")
        return jsc_val
    
    def voc(self, printed: bool = True) -> float:
        """Conducts an open circuit voltage measurement.
        Args:
        -----
            printed (boolean = True): boolean to determine if voc is printed
        Returns:
        --------
            float: Open Circuit Voltage (V)
        """
        self._source_current_measure_voltage()
        self.keithley.source_current = 0
        self.keithley.enable_source()
        voc_val = -self._measure()[0]
        self.keithley.disable_source()
        if printed:
            print(f"Voc: {voc_val*1000:.2f} mV")
        return voc_val
    
    @abstractmethod
    def _measure(self) -> List[numpy.ndarray]:
        """Measures voltage, current, and resistance

        Returns
        -------
        List[numpy.ndarray]
            [voltage (V), current (A), resistance (Ohms)]
        """
        pass

    @abstractmethod
    def _jv_sweep(
        self, 
        vstart: float, 
        vend: float,
        vsteps: int,
        light: bool = True) -> Tuple[list]:
        """Applys voltage sources along a voltage grid, measures current response.
        Returns:
        --------
            tuple: 
                Voltage (V), Current Density (mA/cm2), 
                Current (A), and Measured Voltage (V) 
                arrays plus Light Boolean.
        """
        pass

    @abstractmethod
    def _format_jv(self) -> pandas.DataFrame:
        """Uses output of `_jv_sweep` along with crucial info to preview and save JV data.
        """
        pass
