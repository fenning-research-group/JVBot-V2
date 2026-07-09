from dataclasses import dataclass
import pandas as pd
from datetime import datetime
from ..core.containers import BaseConstantsConfig, ProtocolMetadataConfig
from ..core.measure import BaseExecutor

@dataclass
class VocBufferedConfig(BaseConstantsConfig):
    name: str # sample name
    buffer_points: int = 1
    compliance_voltage: float = 2.0 # V
    printed: bool = True
    preview: bool = False

    def validate(self):
        if self.compliance_voltage <= 0:
            raise ValueError("Compliance voltage must be positive!")
        if self.buffer_points <= 0:
            raise ValueError("Buffer points must be positive!")

class VocBufferedExecutor(BaseExecutor):
    
    def setup_hardware(self, config: VocBufferedConfig, instrument):
        log_str = f"[{config.name}] Setting up SMU for Current Sourcing..."
        # Configure SMU for current sourcing (0 A) and voltage measuring
        instrument.keithley.apply_current()
        instrument.keithley.measure_voltage()
        instrument.keithley.compliance_voltage = config.compliance_voltage
        instrument.keithley.source_current = 0

    def _measure(self, config: VocBufferedConfig, instrument):
        instrument.keithley.config_buffer(config.buffer_points)
        instrument.keithley.start_buffer()
        instrument.keithley.wait_for_buffer()
        return instrument.keithley.means

    def run_measurement(self, config: VocBufferedConfig, instrument) -> dict:
        instrument.keithley.enable_source()
        # Buffered read method (light_JV_legacy style) using _measure helper
        means = self._measure(config=config, instrument=instrument)
        voc_val = means[0]
        return {
            "Voc (V)": voc_val,
            "Timestamp": datetime.now().isoformat(),
            "buffer_points": config.buffer_points,
        }

    def teardown_hardware(self, config: VocBufferedConfig, instrument):
        instrument.keithley.source_current = 0.0
        instrument.keithley.disable_source()

class VocBufferedFormatter:
    """Take the measurement results of the executor and handles logging, saving, and formatting."""
    
    @staticmethod
    def format_and_save(raw_data: dict, config: VocBufferedConfig, instrument):
        voc_val = raw_data["Voc (V)"]
        if config.printed:
            print(f"Voc: {voc_val * 1000:.2f} mV")
            
        # Create DataFrame and save
        data = pd.DataFrame({
            "Timestamp": [raw_data["Timestamp"]],
            "Voc (V)": [voc_val],
            "buffer_points": [raw_data["buffer_points"]],
        })
        
        filename = f"{config.name}_voc_buffered.csv"
        data.to_csv(filename, index=False)
        return data

VOC_BUFFERED_CONTAINER = ProtocolMetadataConfig(
    name = "Buffered Open Circuit Voltage",
    author = "Gemini 3.5 Flash",
    version = "1.0.0",
    description = "Measures Open Circuit Voltage (Voc) via buffer-based reading of the Keithley SMU.",
    references=["Internal Lab Baseline Procedures"],
    protocol_class = VocBufferedExecutor,
    formatter_class = VocBufferedFormatter,
    tags = ["voc", "efficiency"],
    source_code = __file__
)
