from pymeasure.instruments.keithley import Keithley2400
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import time
import csv
import time
from tqdm import tqdm

########################################################
# THIS IS EXPERIMENTAL CODE FOR SCAN RATE AND DARK JVs #
########################################################
class Control_Keithley_Eric:
    def __init__(self, area = 0.048, address = "GPIB0::22::INSTR"):
        self.area = area
        self.pause = 0.001
        self.wires = 4
        self.compliance_current = 1.05
        self.compliance_voltage = 20
        self.counts = 1
        self._scan_speeds = {
            "S": 10,
            "M": 1,
            "F": 0.1,
        }
        self._current_nplc = 1
        self._voltage_nplc = 1
        self._resistance_nplc = 1
        self._source_delay = 0.001
        self._source_delay_auto = True
        self.__previewFigure = None
        self.__previewAxes = None
        self.connect(keithley_address=address)
        self.preview_figs = {}
    def help(self):
        """Prints useful information to terminal
        """
        lines = [
            "Variables\n",
            f"self.area = {self.area}\n",
            f"self.wires = {self.wires}\n",
            f"self.compliance_current = {self.compliance_current}\n",
            f"self.compliance_voltage = {self.compliance_voltage}\n",
        ]
        output = ""
        for L in lines:
            output += L
        print(output)
    def connect(self, keithley_address):
        """Connect to the GPIB interface

        Parameters
        ----------
        keithley_address : str
            GPIB unique identifier of the Keithley
        """
        self.keithley = Keithley2400(keithley_address)
        self.keithley.reset()
        self.keithley.use_front_terminals()
        self.keithley.apply_voltage()
        self.keithley.wires = self.wires
        self.keithley.compliance_current = self.compliance_current
        self.keithley.source_voltage = 0
    def disconnect(self):
        """Disconnects from the GPIB interface
        """
        self.keithley.shutdown()
    def _source_voltage_measure_current(self, NPLC = 1):
        self.keithley.current_nplc = NPLC
        self.keithley.apply_voltage()
        self.keithley.measure_current()
        self.keithley.source_delay_auto = False
        self.keithley.sample_continuously()
        self.keithley.compliance_current = self.compliance_current
        self.keithley.source_voltage = 0
    def _source_current_measure_voltage(self, NPLC = 1):
        self.keithley.voltage_nplc = NPLC
        self.keithley.apply_current()
        self.keithley.measure_voltage()
        self.keithley.source_delay = 0
        self.keithley.source_delay_auto = False
        self.keithley.sample_continuously()
        self.keithley.compliance_voltage = self.compliance_voltage
        self.keithley.source_current = 0
    def _measure(self):
        return self.keithley.read().strip()
    def _execute_step(self, voltage_step, source_delay, measure_duration):
        t0 = time.time()
        self.keithley.source_voltage = voltage_step
        if source_delay > 0:
            time.sleep(source_delay)
        v_delay_ = time.time() - t0
        t0 = time.time()
        t = time.time()
        i = []
        while t - t0 <= measure_duration:
            t = time.time()
            i_ = float(self._measure())
            i.append(i_)
        return np.mean(i), np.std(i), v_delay_, t - t0
    def _jv_sweep(self, vstart, vend, vsteps, source_delay = 0, NPLC = 1, measure_duration = 10, light = True):
        v = np.linspace(vstart, vend, vsteps)
        i = np.zeros((vsteps,))
        i_std = np.zeros((vsteps,))
        v_delay = np.zeros((vsteps,))
        measure_duration_ = np.zeros((vsteps,))
        step_duration = np.zeros((vsteps,))
        self._source_voltage_measure_current(NPLC)
        self.keithley.sourve_voltage = vstart
        self.keithley.enable_source()

        begin_time = time.time()
        t0 = time.time()
        for m, v_ in enumerate(v):
            if m > 0:
                t0 = time.time()
            i[m], i_std[m], v_delay[m], measure_duration_[m] = self._execute_step(v_, source_delay, measure_duration)
            step_duration[m] = time.time() - t0
        end_time = time.time()
        times = end_time - begin_time
        self.keithley.disable_source()
        self.keithley.current_nplc = self._current_nplc
        self.keithley.source_delay = self._source_delay
        self.keithley.source_delay_auto = self._source_delay_auto
        return v, i, i_std, v_delay, measure_duration_, step_duration, light, times
    def _format_jv(self, v, i, i_std, v_delay, measure_duration, step_duration, times, name, light_on_off = True, dir = "fwd", scan_number = "S1", scan_speed = "M", source_delay = None, preview = True):
        """Uses output of _jv_sweep along with crucial info to preview and save JV data

        Parameters
        ----------
        v : np.ndarray(float)
            voltage array
        i : np.ndarray(float)
            current array
        i_std : np.ndarray(float)
            standard deviation of current measurements per voltage step
        v_delay: np.ndarray(float)
            duration of settlement time after applying the fresh voltage step to the cell
        measure_duration : np.ndarray(float)
            duration of measurement period after settlement time finishes
        step_duration : np.ndarray(float)
            full duration of each voltage step (for computing ~V/s rates)
        times : float
            How long the jv sweep took
        name : str
            Name of the device
        light_on_off : bool, optional
            for file name generation, is the solar simulator on? by default True
        dir : str, optional
            for file name generation, was this a Fwd or Rev scan? by default "fwd"
        scan_number : str, optional
            for file name generation, which repeat scan is this? by default "S1"
        scan_speed : str, optional
            for file name generation, are we speedy, average, or leisurely? by default "M"
        source_delay : _type_, optional
            for file name generation, what source_delay/current_settlement duration did this scan plan to use? by default None
        preview : bool, optional
            Should we add the results of the JV sweep onto the previewFigure, previewAxes? by default True
        """
        j = [-i_*1000/self.area for i_ in i]
        j_std = [-i_*1000/self.area for i_ in i_std]
        p = [j_*v_ for j_, v_ in zip(j, v)]
        data = pd.DataFrame(
            {
                "Times (s)": times,
                "Voltage (V)": v,
                "Current Density (mA/cm2)": j,
                "Current (A)": i,
                "Power Density (mW/cm2)": p,
                "Current Settlement Duration (s)": v_delay,
                "Current Measurement Duration (s)": measure_duration,
                "Voltage Step Duration (s)": step_duration,
                "Measured Current Density Standard Deviation (mA/cm2)": j_std,
                "Measured Current Standard Deviation (A)": i_std
            }
        )
        # save csv
        if light_on_off:
            light_on_off = "light"
        else:
            light_on_off = "dark"
        if scan_number is None:
            scan_n = ""
        else:
            scan_n = f"_{scan_number}"
        if scan_speed is None:
            scan_s = ""
        else:
            if isinstance(scan_speed, str):
                scan_s = f"_SS{scan_speed}"
            else:
                sn = f"{scan_speed}"
                if '.' in sn:
                    scan_s = f"_SS{sn.split('.')[0]}-{sn.split('.')[1]}"
                else:
                    scan_s = f"_SS{sn}"
        if source_delay is None:
            scan_d = ""
        else:
            scan_d_ = f"_{source_delay}"
            first, second = scan_d_.split('.')
            scan_d = "{}-{}".format(first, second)
        data.to_csv(f"{name}{scan_n}_{dir}_{light_on_off}{scan_s}{scan_d}.csv")
        if preview:
            self._preview(v, j, 'Voltage (V)', 'Current Density (mA/cm2)', f'{name}{scan_n}_{dir}_{light_on_off}{scan_s}')
    def jv(self, name, direction, scan_number, vmin, vmax, vsteps = 50, speed_opt = "M", source_delay = None, measure_duration = None, light = True, pause = False, preview = True):
        if len(direction) == 3:
            dir_0 = direction; skip_dir_1 = True
        else:
            dir_0 = direction[:3]; skip_dir_1 = False; dir_1 = direction[3:]
        if abs(vmin) < abs(vmax):
            v0 = vmin; v1 = vmax
        elif abs(vmin) > abs(vmax):
            v0 = vmax; v1 = vmin
        # fwd is from low -> high, reverse opposite
        if 'f' in dir_0:
            vstart_0 = v0; vend_0 = v1
            vstart_1 = v1; vend_1 = v0
        else:
            vstart_0 = v0; vend_0 = v1
            vstart_1 = v1; vend_1 = v0
        if speed_opt not in ["M", "S", "F"]:
            raise Exception("The `speed` input must be 'M', 'S', or, 'F', corresponding to Medium, Slow, Fast NPLC measurement rates.")
        NPLC = self._scan_speeds[speed_opt]
        if source_delay is None:
            source_delay = self._source_delay
        if measure_duration is None:
            measure_duration = 10
        scan_n = scan_number
        v, i, i_std, v_delay, measure_duration_, step_duration, light, times = self._jv_sweep(vstart = vstart_0, vend = vend_0, vsteps = vsteps, source_delay = source_delay, measure_duration = measure_duration, NPLC = NPLC, light = light)
        data = self._format_jv(v = v, i = i, i_std = i_std, v_delay = v_delay, measure_duration = measure_duration_, step_duration = step_duration, times = times, name = name, light_on_off = light, dir = dir_0, scan_number = scan_n, scan_speed = speed_opt, source_delay = source_delay, preview = True)
        if not skip_dir_1:
            v, i, i_std, v_delay, measure_duration_, step_duration, light, times = self._jv_sweep(vstart = vstart_1, vend = vend_1, vsteps = vsteps, source_delay = source_delay, measure_duration = measure_duration, NPLC = NPLC, light = light)
            data = self._format_jv(v = v, i = i, i_std = i_std, v_delay = v_delay, measure_duration = measure_duration_, step_duration = step_duration, times = times, name = name, light_on_off = light, dir = dir_1, scan_number = scan_n, scan_speed = speed_opt, source_delay = source_delay, preview = True)

    def jsc(self, printed = True) -> float:
        self._source_voltage_measure_current()
        self.keithley.source_voltage = 0
        self.keithley.enable_source()
        isc = -float(self._measure())
        jsc_val = isc*1000/self.area
        self.keithley.disable_source()
        if printed:
            print(f"Isc: {isc:.3f} A, Jsc: {jsc_val:.2f} mA/cm2")
        return jsc_val
    def voc(self, printed = True) -> float:
        self._source_current_measure_voltage()
        self.source_current = 0
        self.keithley.enable_source()
        voc_val = float(self._measure())
        self.keithley.disable_source()
        if printed:
            print(f"Voc: {voc_val*1000:.2f} mV")
        return voc_val
    def jv_time(self, name, scan_num, vstart, vend, vsteps, NPLC, step_duration, source_delay):
        ts = []
        vs = []
        js = []
        t_total = []
        v_total = []
        j_total = []
        if vstart > vend:
            dir = 'rev'
        else:
            dir = 'fwd'
        self.keithley.source_delay = source_delay
        v = np.linspace(vstart, vend, vsteps)
        self._source_voltage_measure_current(NPLC)
        self.keithley.source_voltage = vstart
        self.keihtley.enable_source()
        t0 = time.time()
        print('Starting JV Sweep.')
        for m, v_ in enumerate(v):
            print(f"\tExecuting step {m+1}/{len(v)} now.")
            self.keithley.source_voltage = v_
            t_step_0 = time.time()
            j_step = []
            v_step = []
            t_step = []
            while time.time() - t_step_0 <= step_duration:
                j_ = -1000*float(self._measure())/self.area
                j_step.append(j_)
                v_step.append(v_)
                t_step.appen(time.time() - t_step_0)
                j_total.append(j_)
                v_total.append(v_)
                t_total.append(time.time() - t0)
            ts.append(t_step)
            js.append(j_step)
            vs.append(v_step)
        self.keithley.disable_source()
        self.keithley.current_nplc = self._current_nplc
        self.keithley.source_delay = self._source_delay
        self.keithley.source_delay_auto = self._source_delay_auto
        data = pd.DataFrame(
            {
                "Time (s)": t_total,
                "Voltage (V)": v_total,
                "Current Density (mA/cm2)": j_total,
                # "Stepwise Time (s)": ts,
                # "Stepwise Voltage (V)": vs,
                # "Stepwise Current Density (mA/cm2)": js,
            }
        )
        NPLC_str = str(NPLC)
        if '.' in NPLC_str:
            NPLC_str.replace('.', '-')
        stepdur = str(step_duration)
        if '.' in stepdur:
            stepdur.replace('.', '-')
        filename = f"{name}_{scan_num}_{dir}_NPLC-{NPLC_str}_StepDuration-{step_duration}.json"
        data.to_json(filename)
    def jv_rates(self, name, scan_rates, repeat_scans, vstart, vend, vsteps, directions, NPLC = 1, measurement_duration = 0.1, delay_measure_split = None, light = True):
        for d_idx, direction in enumerate(directions):
            print(f"Working on direction set {d_idx+1}/{len(directions)}")
            if len(direction) == 3:
                dir_0 = direction; skip_dir_1 = True
            else:
                dir_0 = direction[:3]; skip_dir_1 = False; dir_1 = direction[3:]
            if abs(vstart) < abs(vend):
                v0 = vstart; v1 = vend
            elif abs(vstart) > abs(vend):
                v0 = vend; v1 = vstart
            if 'f' in dir_0:
                vstart_ = v0; vend_0 = v1
            ### Line 376 of O.G. control5.py file