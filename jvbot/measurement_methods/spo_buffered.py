from dataclasses import dataclass
import pandas as pd
import time
from datetime import datetime
import matplotlib.pyplot as plt
from ..core.containers import BaseConstantsConfig, ProtocolMetadataConfig
from ..core.measure import BaseExecutor

@dataclass
class SpoBufferedConfig(BaseConstantsConfig):
    name: str # sample name
    vstart: float # V
    vstep: float # V
    vdelay: float # s
    interval: float # s
    interval_count: int
    buffer_points: int = 2
    compliance_current: float = 1.05 # A
    area: float = 0.048 # cm2
    printed: bool = True
    preview: bool = True
    task_id: str = None

    def validate(self):
        if self.compliance_current <= 0:
            raise ValueError("Compliance current must be positive!")
        if self.area <= 0:
            raise ValueError("Active pixel area must be positive!")
        if self.buffer_points <= 0:
            raise ValueError("Buffer points must be positive!")
        if self.interval <= 0:
            raise ValueError("Interval must be positive!")
        if self.interval_count <= 0:
            raise ValueError("Interval count must be positive!")

class SpoBufferedExecutor(BaseExecutor):
    
    def setup_hardware(self, config: SpoBufferedConfig, instrument):
        log_str = f"[{config.name}] Setting up SMU for SPO tracking..."
        # Configure SMU for voltage sourcing (0 V) and current measuring
        instrument.keithley.apply_voltage()
        instrument.keithley.measure_current()
        instrument.keithley.compliance_current = config.compliance_current
        instrument.keithley.source_voltage = 0

    def _measure(self, config: SpoBufferedConfig, instrument):
        instrument.keithley.config_buffer(config.buffer_points)
        instrument.keithley.start_buffer()
        instrument.keithley.wait_for_buffer()
        return instrument.keithley.means

    def run_measurement(self, config: SpoBufferedConfig, instrument) -> dict:
        instrument.keithley.enable_source()
        
        # Setup for MPP tracking
        v = [] # applied voltage
        vmeas = [] # measured voltage
        i = [] # negative-flipped current
        t = [] # time elapsed
        
        vapplied = config.vstart
        stime = time.time()
        ctime = time.time() - stime
        n = 0
        
        # Step 1: Make two initial measurements to establish a baseline trend
        while ctime < config.interval * 2:
            if ctime <= n * config.interval:
                time.sleep(1e-3)
            else:
                instrument.keithley.source_voltage = vapplied
                time.sleep(config.vdelay)
                tempv, tempi, _ = self._measure(config, instrument)
                vmeas.append(tempv)
                v.append(vapplied)
                i.append(-1 * tempi)
                t.append(ctime)
                if config.printed:
                    print(vapplied, tempv, tempi, v)
                n += 1
                vapplied += config.vstep
            ctime = time.time() - stime
            
        # Step 2: Perturb and Observe loop
        while ctime < config.interval * config.interval_count:
            if ctime < config.interval * n:
                time.sleep(1e-3)
            else:
                # Calculate last two power levels
                p0 = vmeas[-2] * i[-2]
                p1 = vmeas[-1] * i[-1]
                
                # Iterate voltage step direction
                if p1 <= p0: # power decreased
                    if v[-1] < v[-2]: # voltage decreased
                        vapplied += config.vstep
                    else:
                        vapplied -= config.vstep
                else: # power increased
                    if v[-1] > v[-2]: # voltage increased
                        vapplied += config.vstep
                    else:
                        vapplied -= config.vstep
                        
                # Apply voltage and measure current/voltage
                instrument.keithley.source_voltage = vapplied
                time.sleep(config.vdelay)
                tempv, tempi, _ = self._measure(config, instrument)
                
                vmeas.append(tempv)
                v.append(vapplied)
                i.append(-1 * tempi)
                t.append(ctime)
                if config.printed:
                    print(f'Vapplied: {1000*vapplied:.01f}mV, PCE: {-1000*vapplied*tempi/config.area:0.2f}%')
                n += 1
            ctime = time.time() - stime
            
        instrument.keithley.disable_source()
        return {
            "v": v,
            "i": i,
            "vmeas": vmeas,
            "t": t,
        }

    def teardown_hardware(self, config: SpoBufferedConfig, instrument):
        instrument.keithley.source_voltage = 0.0
        instrument.keithley.disable_source()

class SpoBufferedFormatter:
    """Take the measurement results of the executor and handles logging, saving, and formatting."""
    
    @staticmethod
    def _preview(xd, yd, xl, yl, label):
        try:
            plt.ioff()
            fig, ax = plt.subplots()
            ax.plot(xd, yd, label=label)
            ax.set_xlabel(xl)
            ax.set_ylabel(yl)
            ax.legend()
            plt.ion()
            plt.show()
            time.sleep(1e-4)
        except Exception as e:
            print(f"Could not render plot preview: {e}")

    @staticmethod
    def format_and_save(raw_data: dict, config: SpoBufferedConfig, instrument):
        v = raw_data["v"]
        i = raw_data["i"]
        vmeas = raw_data["vmeas"]
        t = raw_data["t"]
        
        j = []
        for value in i:
            j.append(-value * 1000 / config.area) # sign flip for solar cell current convention
            
        p = [num1 * num2 for num1, num2 in zip(j, vmeas)]
        
        data = pd.DataFrame({
            "Voltage (V)": v,
            "Current Density (mA/cm2)": j,
            "Measured Voltage (V)": vmeas,
            "Current (A)": i,
            "Power Density (mW/cm2)": p,
            "Time Elasped (s)": t, # Spelling matched to original light_JV_legacy
        })
        
        filename = f"{config.name}_SPO.csv"
        data.to_csv(filename, index=False)
        
        if config.preview:
            SpoBufferedFormatter._preview(t, p, 'Time (s)', 'Power (mW/cm2)', filename.replace('.csv', ''))
            
        return data

SPO_BUFFERED_CONTAINER = ProtocolMetadataConfig(
    name = "Buffered Stable Power Output",
    author = "Gemini 3.5 Flash",
    version = "1.0.0",
    description = "Tracks maximum power point (MPP) over time using a Perturb & Observe algorithm with buffer-averaged readings.",
    references=["Internal Lab Baseline Procedures"],
    protocol_class = SpoBufferedExecutor,
    formatter_class = SpoBufferedFormatter,
    tags = ["spo", "efficiency", "mpp"],
    source_code = __file__
)
