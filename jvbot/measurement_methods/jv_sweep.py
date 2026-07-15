from dataclasses import dataclass
import numpy as np
from typing import Literal
import pandas as pd
import time
import matplotlib.pyplot as plt
from ..core.containers import BaseConstantsConfig, ProtocolMetadataConfig
from ..core.measure import BaseExecutor

@dataclass
class JVSweepConfig(BaseConstantsConfig):
    name: str # sample name
    direction: Literal["fwd", "rev", "fwdrev", "revfwd"]
    vmin: float
    vmax: float
    vsteps: int = 50
    light: bool = True
    preview: bool = True
    area: float = 0.0448 # cm2
    buffer_points: int = 1
    task_id: str = None

    def validate(self):
        if self.vsteps <= 1:
            raise ValueError(f"Can't have less than 1 voltage step in between Start {self.vmin} and Stop {self.vmax}!")
        if self.area <= 0:
            raise ValueError(f"Active Area of pixels must be positive.")

class JVSweepExecutor(BaseExecutor):

    def setup_hardware(self, config: JVSweepConfig, instrument):
        log_str = "[{config.name}] Setting up SMU for Voltage Sourcing..."
        # Set up sourcing voltage and measuring current
        instrument.keithley.apply_voltage()
        instrument.keithley.measure_current()
        instrument.keithley.compliance_current = config.compliance_current
        instrument.keithley.source_voltage = 0

    def _measure(self, config: JVSweepConfig, instrument):
        """
            Measures voltage, current, and resistance
        """
        instrument.keithley.config_buffer(config.buffer_points)
        instrument.keithley.start_buffer()
        instrument.keithley.wait_for_buffer()
        return instrument.keithley.means

    def _run_single_sweep(self, vstart: float, vend: float, config: JVSweepConfig, instrument, direction):
        # prep data containers
        v = np.linspace(vstart, vend, config.vsteps)
        vmeas = np.zeros((config.vsteps,))
        i = np.zeros((config.vsteps,))
        
        # start scan
        instrument.keithley.source_voltage = vstart
        instrument.keithley.enable_source()

        for m, v_ in enumerate(v):
            instrument.keithley.source_voltage = v_
            vmeas[m], i[m], _ = self._measure(config = config, instrument = instrument)
        instrument.keithley.disable_source()
        return {
            "Applied Voltage (V)": v, 
            "Measured Current (A)": i, 
            "Measured Voltage (V)": vmeas,
            "direction": direction,
            "light": config.light,
        }

    def run_measurement(self, config, instrument):
        # fwd is going to be from the lower abs v to higher abs v, reverse will be opposite
        if abs(config.vmin) < abs(config.vmax):
            v0 = config.vmin
            v1 = config.vmax
        else:
            v0 = config.vmax; v1 = config.vmin
        if config.direction == "fwd":
            return self._run_single_sweep(vstart = v0, vend = v1, config = config, instrument = instrument)
        elif config.direction == "rev":
            return self._run_single_sweep(vstart = v1, vend = v0, config = config, instrument = instrument)
        elif config.direction in ["fwdrev", "revfwd"]:
            first_dir = "fwd" if config.direction == "fwdrev" else "rev"
            second_dir = "rev" if config.direction == "fwdrev" else "fwd"

            # sweep 1
            start1, end1 = (v0, v1) if first_dir == "fwd" else (v1, v0)
            res1 = self._run_single_sweep(vstart = start1, vend = end1, config = config, instrument = instrument, direction = first_dir)
            start2, end2 = (v1, v0) if second_dir == "rev" else (v0, v1)
            res2 = self._run_single_sweep(vstart = start2, vend = end2, config = config, instrument = instrument, direction = second_dir)
            return {f"scan-{first_dir}": res1, f"scan-{second_dir}": res2}

    def teardown_hardware(self, config, instrument):
        instrument.keithley.source_voltage = 0.0
        instrument.keithley.disable_source()

class JVSweepFormatter:
    """Take the measurement results of the executor and handles math, file saving, and plotting."""
    def _preview(self,xd,yd,xl,yl,label):
        """
            Appends the [xd,yd] arrays to preview window with labels [xl,yl] and trace label label.
            
            Args:
                xd (list): x value
                yd (list): y value
                yl (string): y label
                xl (string): xlabel
                label (string): label for graph
        """
        def handle_close(evt, self):
            del self.preview_figs[f'{xl},{yl}']
            
        try:
            getattr(self, "preview_figs")
        except:
            self.preview_figs = {}


        if f'{xl},{yl}' not in self.preview_figs.keys():
            plt.ioff()
            self.__previewFigure, self.__previewAxes = plt.subplots()
            self.__previewFigure.canvas.mpl_connect('close_event', lambda x: handle_close(x, self))	# if preview figure is closed, lets clear the figure/axes handles so the next preview properly recreates the handles
            self.__previewAxes.set_xlabel(xl)
            self.__previewAxes.set_ylabel(yl)
            self.__previewAxes.set_ylim(0,30)
            self.__previewAxes.set_xlim(-.2,2)
            plt.ion()
            plt.show()
            self.preview_figs[f'{xl},{yl}'] = [self.__previewFigure, self.__previewAxes]

        if len(xd) == 1:
            self.preview_figs[f'{xl},{yl}'][1].scatter([xd],[yd], label = label)
        else:
            self.preview_figs[f'{xl},{yl}'][1].plot(xd,yd, label = label)
        self.preview_figs[f'{xl},{yl}'][1].legend()
        self.preview_figs[f'{xl},{yl}'][0].canvas.draw()
        self.preview_figs[f'{xl},{yl}'][0].canvas.flush_events()
        time.sleep(1e-4)		#pause allows plot to update during series of measurements 

    @staticmethod
    def format_and_save(raw_data: dict, config: JVSweepConfig, instrument, scan_number: int = None):
        # Handle composite double sweeps recursively if nested
        if "scans" in raw_data:
            dfs = []
            for idx, scan in enumerate(raw_data["scans"]):
                df = JVSweepFormatter.format_and_save(scan, config, instrument, scan_number=idx+1)
                dfs.append(df)
            return dfs

        # Extract vectors
        v = raw_data["Applied Voltage (V)"]
        i = raw_data["Measured Current (A)"]
        vmeas = raw_data["Measured Voltage (V)"]

        # Calculate current density (sign flipped for standard photovoltaic conventions)
        j = [-val * 1000 / config.area for val in i]
        p = [num1 * num2 for num1, num2 in zip(j, vmeas)]

        data = pd.DataFrame({
            'Voltage (V)': v,
            'Current Density (mA/cm2)': j,
            'Current (A)': i,
            'Measured Voltage (V)': vmeas,
            'Power Density (mW/cm2)': p,
        })

        light_str = "light" if raw_data["light"] else "dark"
        scan_suffix = f"_{scan_number}" if scan_number is not None else ""
        filename = f"{config.name}{scan_suffix}_{raw_data['direction']}_{light_str}.csv"
        data.to_csv(filename, index = False)
        if config.preview:
            JVSweepFormatter._preview( v, j, 'Voltage (V)', 'Current Density (mA/cm2)', filename.replace('.csv', ''))
        return data



JV_SWEEP_CONTAINER = ProtocolMetadataConfig(
    name = "Legacy J-V Sweep",
    author = "Lab Legacy circa 2024",
    version = "2.0.0",
    description = "Sweeps source voltages across 4-wire configuration to calculate solar cell performance.",
    references=["Internal Lab Baseline Procedures"],
    protocol_class = JVSweepExecutor,
    formatter_class = JVSweepFormatter,
    tags = ["jv", "efficiency"]
)