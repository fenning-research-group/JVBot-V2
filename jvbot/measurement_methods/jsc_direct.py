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
        print(f"jsc executor: setting up hardware for {config.name}")
        try:
            instrument.keithley.current_nplc = config.nplc
            print(f"jsc executor: set current_nplc to {config.nplc}")
            instrument.keithley.apply_voltage()
            print("jsc executor: applied voltage mode")
            instrument.keithley.measure_current()
            print("jsc executor: enabled current measurement")
            instrument.keithley.source_delay_auto = False
            instrument.keithley.compliance_current = config.compliance_current
            print(f"jsc executor: compliance current set to {config.compliance_current}")
            instrument.keithley.source_voltage = 0
            print("jsc executor: source voltage set to 0v")
        except Exception as e:
            print(f"jsc executor error: setup hardware failed with: {e}")
            raise e

    def _measure(self, config: JscDirectConfig, instrument):
        print("jsc executor: reading from keithley...")
        raw_val = instrument.keithley.read().strip()
        print(f"jsc executor: raw value read from keithley: '{raw_val}'")
        return raw_val

    def run_measurement(self, config: JscDirectConfig, instrument) -> dict:
        print("jsc executor: enabling keithley source")
        try:
            instrument.keithley.enable_source()
        except Exception as e:
            print(f"jsc executor error: failed to enable source: {e}")
            raise e
            
        try:
            raw_measure = self._measure(config=config, instrument=instrument)
            print(f"jsc executor: parsing raw measurement string to float: '{raw_measure}'")
            isc = -float(raw_measure)
            jsc_val = isc * 1000 / config.area
            print(f"jsc executor: calculation successful. isc={isc} a, jsc={jsc_val} ma/cm2 (area={config.area})")
        except Exception as e:
            print(f"jsc executor error: run_measurement calculation/parse failed: {e}")
            raise e
            
        return {
            "Isc (A)": isc,
            "Jsc (mA/cm2)": jsc_val,
            "Timestamp": datetime.now().isoformat(),
        }

    def teardown_hardware(self, config: JscDirectConfig, instrument):
        print("jsc executor: disabling source")
        try:
            instrument.keithley.disable_source()
            print("jsc executor: source disabled successfully")
        except Exception as e:
            print(f"jsc executor error: failed to disable source: {e}")
            raise e

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
