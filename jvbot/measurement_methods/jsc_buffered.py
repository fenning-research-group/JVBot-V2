from dataclasses import dataclass
import pandas as pd
from datetime import datetime
from ..core.containers import BaseConstantsConfig, ProtocolMetadataConfig
from ..core.measure import BaseExecutor

@dataclass
class JscBufferedConfig(BaseConstantsConfig):
    name: str # sample name
    buffer_points: int = 2
    compliance_current: float = 1.05 # A
    area: float = 0.048 # cm2
    printed: bool = True
    preview: bool = False
    task_id: str = None

    def validate(self):
        if self.compliance_current <= 0:
            raise ValueError("Compliance current must be positive!")
        if self.area <= 0:
            raise ValueError("Active pixel area must be positive!")
        if self.buffer_points <= 0:
            raise ValueError("Buffer points must be positive!")

class JscBufferedExecutor(BaseExecutor):
    
    def setup_hardware(self, config: JscBufferedConfig, instrument):
        log_str = f"[{config.name}] Setting up SMU for Current Measuring..."
        # Configure SMU for voltage sourcing (0 V) and current measuring
        instrument.keithley.apply_voltage()
        instrument.keithley.measure_current()
        instrument.keithley.compliance_current = config.compliance_current
        instrument.keithley.source_voltage = 0

    def _measure(self, config: JscBufferedConfig, instrument):
        instrument.keithley.config_buffer(config.buffer_points)
        instrument.keithley.start_buffer()
        instrument.keithley.wait_for_buffer()
        return instrument.keithley.means

    def run_measurement(self, config: JscBufferedConfig, instrument) -> dict:
        instrument.keithley.enable_source()
        # Buffered read method (light_JV_legacy style) using _measure helper
        means = self._measure(config=config, instrument=instrument)
        isc = -means[1]
        jsc_val = isc * 1000 / config.area
        return {
            "Isc (A)": isc,
            "Jsc (mA/cm2)": jsc_val,
            "Timestamp": datetime.now().isoformat(),
            "buffer_points": config.buffer_points,
        }

    def teardown_hardware(self, config: JscBufferedConfig, instrument):
        instrument.keithley.disable_source()

class JscBufferedFormatter:
    """Take the measurement results of the executor and handles logging, saving, and formatting."""
    
    @staticmethod
    def format_and_save(raw_data: dict, config: JscBufferedConfig, instrument):
        isc = raw_data["Isc (A)"]
        jsc_val = raw_data["Jsc (mA/cm2)"]
        if config.printed:
            print(f"Isc: {isc:.3f} A, Jsc: {jsc_val:.2f} mA/cm2")
            
        # Create DataFrame and save
        data = pd.DataFrame({
            "Timestamp": [raw_data["Timestamp"]],
            "Isc (A)": [isc],
            "Jsc (mA/cm2)": [jsc_val],
            "Active Area (cm2)": [config.area],
            "buffer_points": [raw_data["buffer_points"]],
        })
        
        filename = f"{config.name}_jsc_buffered.csv"
        data.to_csv(filename, index=False)
        return data

JSC_BUFFERED_CONTAINER = ProtocolMetadataConfig(
    name = "Buffered Short Circuit Current Density",
    author = "Gemini 3.5 Flash",
    version = "1.0.0",
    description = "Measures Short Circuit Current Density (Jsc) via buffer-based reading of the Keithley SMU.",
    references=["Internal Lab Baseline Procedures"],
    protocol_class = JscBufferedExecutor,
    formatter_class = JscBufferedFormatter,
    tags = ["jsc", "efficiency"],
    source_code = __file__
)
