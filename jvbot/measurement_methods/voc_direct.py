from dataclasses import dataclass
import pandas as pd
from datetime import datetime
from ..core.containers import BaseConstantsConfig, ProtocolMetadataConfig
from ..core.measure import BaseExecutor

@dataclass
class VocDirectConfig(BaseConstantsConfig):
    name: str # sample name
    compliance_voltage: float = 20.0 # V
    nplc: float = 1.0
    source_delay: float = 0.0
    source_delay_auto: bool = False
    printed: bool = True
    preview: bool = False

    def validate(self):
        if self.compliance_voltage <= 0:
            raise ValueError("Compliance voltage must be positive!")

class VocDirectExecutor(BaseExecutor):
    
    def setup_hardware(self, config: VocDirectConfig, instrument):
        log_str = f"[{config.name}] Setting up SMU for Current Sourcing..."
        # Configure SMU for current sourcing (0 A) and voltage measuring (control5 style)
        instrument.keithley.voltage_nplc = config.nplc
        instrument.keithley.apply_current()
        instrument.keithley.measure_voltage()
        instrument.keithley.source_delay = config.source_delay
        instrument.keithley.source_delay_auto = config.source_delay_auto
        instrument.keithley.sample_continuously()
        instrument.keithley.compliance_voltage = config.compliance_voltage
        instrument.keithley.source_current = 0

    def _measure(self, config: VocDirectConfig, instrument):
        return instrument.keithley.read().strip()

    def run_measurement(self, config: VocDirectConfig, instrument) -> dict:
        instrument.keithley.enable_source()
        # Direct read method (no buffer, control5 style) using _measure helper
        voc_val = float(self._measure(config=config, instrument=instrument))
        return {
            "Voc (V)": voc_val,
            "Timestamp": datetime.now().isoformat(),
        }

    def teardown_hardware(self, config: VocDirectConfig, instrument):
        instrument.keithley.source_current = 0.0
        instrument.keithley.disable_source()

class VocDirectFormatter:
    """Take the measurement results of the executor and handles logging, saving, and formatting."""
    
    @staticmethod
    def format_and_save(raw_data: dict, config: VocDirectConfig, instrument):
        voc_val = raw_data["Voc (V)"]
        if config.printed:
            print(f"Voc: {voc_val * 1000:.2f} mV")
            
        # Create DataFrame and save
        data = pd.DataFrame({
            "Timestamp": [raw_data["Timestamp"]],
            "Voc (V)": [voc_val],
        })
        
        filename = f"{config.name}_voc_direct.csv"
        data.to_csv(filename, index=False)
        return data

VOC_DIRECT_CONTAINER = ProtocolMetadataConfig(
    name = "Direct Open Circuit Voltage",
    author = "Gemini 3.5 Flash",
    version = "1.0.0",
    description = "Measures Open Circuit Voltage (Voc) via immediate direct-read of the Keithley SMU.",
    references=["Internal Lab Baseline Procedures"],
    protocol_class = VocDirectExecutor,
    formatter_class = VocDirectFormatter,
    tags = ["voc", "efficiency"],
    source_code = __file__
)
