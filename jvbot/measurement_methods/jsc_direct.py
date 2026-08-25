from dataclasses import dataclass
import pandas as pd
from datetime import datetime
from ..core.containers import BaseConstantsConfig, ProtocolMetadataConfig
from ..core.measure import BaseExecutor

@dataclass
class JscDirectConfig(BaseConstantsConfig):
    name: str # sample name
    compliance_current: float = 1.05 # A
    area: float = 0.048 # cm2
    nplc: float = 1.0
    printed: bool = True
    preview: bool = False
    task_id: str = None

    def validate(self):
        if self.compliance_current <= 0:
            raise ValueError("Compliance current must be positive!")
        if self.area <= 0:
            raise ValueError("Active pixel area must be positive!")

class JscDirectExecutor(BaseExecutor):
    
    def setup_hardware(self, config: JscDirectConfig, instrument):
        log_str = f"[{config.name}] Setting up SMU for Current Measuring..."
        # Configure SMU for voltage sourcing (0 V) and current measuring (control5 style)
        instrument.keithley.current_nplc = config.nplc
        instrument.keithley.apply_voltage()
        instrument.keithley.measure_current()
        instrument.keithley.source_delay_auto = False
        instrument.keithley.compliance_current = config.compliance_current
        instrument.keithley.source_voltage = 0

    def _measure(self, config: JscDirectConfig, instrument):
        return instrument.keithley.read().strip()

    def run_measurement(self, config: JscDirectConfig, instrument) -> dict:
        instrument.keithley.enable_source()
        # Direct read method (no buffer, control5 style) using _measure helper
        isc = -float(self._measure(config=config, instrument=instrument))
        jsc_val = isc * 1000 / config.area
        return {
            "Isc (A)": isc,
            "Jsc (mA/cm2)": jsc_val,
            "Timestamp": datetime.now().isoformat(),
        }

    def teardown_hardware(self, config: JscDirectConfig, instrument):
        instrument.keithley.disable_source()

class JscDirectFormatter:
    """Take the measurement results of the executor and handles logging, saving, and formatting."""
    
    @staticmethod
    def format_and_save(raw_data: dict, config: JscDirectConfig, instrument):
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
        })
        
        filename = f"{config.name}_jsc_direct.csv"
        data.to_csv(filename, index=False)
        return data

JSC_DIRECT_CONTAINER = ProtocolMetadataConfig(
    name = "Direct Short Circuit Current Density",
    author = "Gemini 3.5 Flash",
    version = "1.0.0",
    description = "Measures Short Circuit Current Density (Jsc) via immediate direct-read of the Keithley SMU.",
    references=["Internal Lab Baseline Procedures"],
    protocol_class = JscDirectExecutor,
    formatter_class = JscDirectFormatter,
    tags = ["jsc", "efficiency"],
    source_code = __file__
)
