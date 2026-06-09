from pymeasure.instruments.keithley import Keithley2400
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import time
import csv


class Control_Keithley:

    def __init__(self, area = 0.048, address='GPIB0::22::INSTR'):
        """
            Initialize Keithley 2400 class SMUs

        Parameters
        ----------
        area : float, optional
            active area of a pixel of some device under test, by default 0.048
        address : str, optional
            SMU address to connect to, by default 'GPIB0::22::INSTR'
        """
        self.area = area
        self.wires = 4
        self.compliance_current = 1.05 # A
        self.compliance_voltage = 2 # V
        self.buffer_points = 2
        self._scan_speeds = { # changes NPLC for measurement
            "H": [0.1, 0.1, 0.1], # [I, V, R]
            "M": [1, 1, 1], # [I, V, R]
            "L": [10, 10, 10], # [I, V, R]
        }
        self._current_nplc = 1
        self._voltage_nplc = 1
        self._resistance_nplc = 1
        self._source_delay = 0.001
        self.__previewFigure = None
        self.__previewAxes = None
        self.connect(keithley_address = address)
        self.preview_figs = {}
    def help(self):
        """
            Prints useful information to terminal
        """
        output = f"Variables\n"
        output += f"self.area = {self.area}\n"
        output += f"self.wires = {self.wires}\n"
        output += f"self.compliance_current = {self.compliance_current}\n"
        output += f"self.compliance_voltage = {self.compliance_voltage}\n"
        print(output)
    def connect(self, keithley_address):
        """Connects to the GPIB interface

        Parameters
        ----------
        keithley_address : str
            GPIB address to search for.
        """
        self.keithley = Keithley2400(keithley_address)
        self.keithley.reset()
        self.keithley.use_front_terminals()
        self.keithley.apply_voltage()
        self.keithley.wires = self.wires
        self.keithley.compliance_current = self.compliance_current
        self.keithley.buffer_points = self.buffer_points
        self.keithley.source_voltage = 0

    def disconnect(self):
        """Disconnects from the GPIB interface
        """
        self.keithley.shutdown()
    def _source_voltage_measure_current(self):
        """
            Sets up sourcing voltage and measuring current
        """
        self.keithley.apply_voltage()
        self.keithley.measure_current()
        self.keithley.compliance_current = self.compliance_current
        self.keithley.source_voltage = 0
    def _source_current_measure_voltage(self):
        """
            Sets up sourcing current and measuring voltage
        """
        self.keithley.apply_current()
        self.keithley.measure_voltage()
        self.keithley.compliance_voltage = self.compliance_voltage
        self.keithley.source_current = 0
    def _measure(self):
        """
            Measures voltage, current, and resistance
            Returns:
                list(np.ndarray): voltage (V), current (A), resistance (Ohms)
        """
        self.keithley.config_buffer(self.buffer_points)
        self.keithley.start_buffer()
        self.keithley.wait_for_buffer()
        return self.keithley.means
    
    def _measure_2(self, **kwargs):
        counts = kwargs.get('buffer_counts', self.buffer_points)
        trigger_delay = kwargs.get('trigger_delay', 0) # auto-set to 0 in keithley already
        timeout = kwargs.get('buffer_timeout', 60) # stop the buffer after this many seconds
        interval = kwargs.get('buffer_interval', 0.1) # how many seconds between pings to check if buffer is full
        self.keithley.config_buffer(points = counts, delay = trigger_delay)
        t0_ = time.time()
        self.keithley.start_buffer()
        self.keithley.wait_for_buffer(timeout = timeout, interval = interval)
        b_t = time.time() - t0_
        return self.keithley.means, self.keithley.standard_devs, b_t
    def _jv_sweep_2(self, vstart, vend, vsteps, source_delay, buffer_counts, NPLC = [1, 1, 1], delay_time = 0.001, trigger_time = 0, light = True):
        # initialize arrays:
        v = np.linspace(vstart, vend, vsteps)
        vmeas = np.zeros((vsteps,))
        i = np.zeros((vsteps,))
        v_duration  = np.zeros((vsteps,))
        vmeas_std = np.zeros((vsteps,))
        i_std = np.zeros((vsteps,))
        buffer_times = np.zeros((vsteps,))
        # set scan settings:
        i_n, v_n, r_n = NPLC
        self.keithley.current_nplc = i_n
        self.keithley.voltage_nplc = v_n
        self.keithley.resistance_nplc = r_n
        self.keithley.source_delay = source_delay # seconds
        # set scan:
        self._source_voltage_measure_current()
        t0 = time.time()
        self.keithley.source_voltage = vstart
        self.keithley.enable_source()
        for m, v_ in enumerate(v):
            if m > 0:
                t0 = time.time()
            self.keithley.source_voltage = v_
            means, std, b_t = self._measure_2(buffer_counts = buffer_counts, trigger_time = trigger_time)
            vmeas[m], i[m], _ = means
            vmeas_std[m], i_std[m], _ = std
            v_duration[m] = time.time() - t0
            buffer_times[m] = b_t
        self.keithley.disable_source()
        # re-set to defaults:
        self.keithley.current_nplc = self._current_nplc
        self.keithley.voltage_nplc = self._voltage_nplc
        self.keithley.resistance_nplc = self._resistance_nplc
        self.keithley.source_delay = self._source_delay
        return v, i, vmeas, vmeas_std, i_std, v_duration, buffer_times, light
    def _format_jv_2(self, v, i, vmeas, vmeas_std, i_std, v_duration, source_delay, buffer_times, light, name, dir, scan_number, scan_speed, preview = True):
        """Uses output of `_jv_sweep` along with crucial info to preview and save JV data.

        Parameters
        ----------
        v : np.ndarray(float)
            voltage array (output from _sweep_jv_2)
        i : np.ndarray(float)
            current array (output from _sweep_jv_2)
        vmeas : np.ndarray(float)
            measured voltage array (output from _sweep_jv_2)
        vmeas_std : np.ndarray(float)
            measured voltage standard deviation array (output from _sweep_jv_2)
        i_std : np.ndarray(float)
            measured current standard deviation array (output from _sweep_jv_2)
        v_duration : np.ndarray(float)
            Duration of each voltage step (output from _sweep_jv_2)
        source_delay : float
            Duration of source delay step of SMU cycle (seconds)
        buffer_times : np.ndarray(float)
            How long the buffer was open for during each voltage step (output from _sweep_jv_2)
        light : bool
            boolean to describe if light was turned on.
        name : str
            name of the device
        dir : str
            direction -- fwd or rev
        scan_number : int
            suffix for multiple scans in a row
        scan_speed : str
            scan rate is Low (L), Medium (M), or High (H)
        preview : bool, optional
            option to preview in graph, by default True
        """
        j = []
        j_std = []
        for i_, i_std_ in zip(i, i_std):
            j.append(-i_*1000/self.area) # amps to mA/cm2, sign flip for solar cell current convention
            j_std.append(i_std_*1000/self.area) # assumed 0 error in area measurement.
        p = [j_*v_ for j_, v_ in zip(j, vmeas)] # mW/cm2
        p_std = [
            (j_*v_)*np.sqrt(
                ((v_std**2)/v_) + ((j_std**2)/j_)
            )
            for j_, j_std, v_, v_std in zip(
                j, j_std, vmeas, vmeas_std
            )
        ]
        data = pd.DataFrame({
            "Voltage (V)": v,
            "Current Density (mA/cm2)": j,
            "Measured Voltage (V)": vmeas,
            "Current (A)": i,
            "Power Density (mW/cm2)": p,
            "Voltage Step Duration (s)": v_duration,
            "Voltage Step Measurement Buffer Duration (s)": buffer_times,
            "Measured Voltage Standard Deviation (V)": vmeas_std,
            "Measured Current Density Standard Deviation (mA/cm2)": j_std,
            "Measured Current Standard Deviation (A)": i_std,
            "Power Density Standard Deviation (mW/cm2)": p_std
        })
        # save csv file
        if light: light_on_off = "light"
        else: light_on_off = "dark"
        if scan_number is None:
            scan_n = ""
        else:
            scan_n = f"_{scan_number}"
        if scan_speed is None:
            scan_s = ""
        else:
            scan_s = f"_{scan_speed}"
        if source_delay is None:
            scan_d = ""
        else:
            scan_d_ = f"_{source_delay}"
            first, second = scan_d_.split(".")
            scan_d = "{}-{}".format(first, second)
        data.to_csv(f"{name}{scan_n}_{dir}_{light_on_off}{scan_s}{scan_d}.csv")
        # preview
        if preview:
            self._preview(v, j, 'Voltage (V)', 'Current Density (mA/cm2)', f'{name}{scan_n}_{dir}){light_on_off}{scan_s}')
    def _preview(self,xd,yd,xl,yl,label):
        """Appends the [xd, yd] arrays to preview window wiht labels [xl, yl] and trace label label.

        Parameters
        ----------
        xd : list
            x values
        yd : list
            y values
        xl : str
            x axis label
        yl : str
            y axis label
        label : str
            [xd,yd] legend label
        """
        def handle_close(evt, self):
            del self.preview_figs[f'{xl},{yl}']
        if f'{xl},{yl}' not in self.preview_figs.keys():
            plt.ioff()
            self.__previewFigure, self.__previewAxes = plt.subplots()
            self.__previewFigure.canvas.mpl_connect('close_event', lambda x: handle_close(x, self)) # if preview figure is closed, lets clear the figure/axes handles so the next preview properly recreates the handles
            self.__previewAxes.set_xlabel(xl)
            self.__previewAxes.set_ylabel(yl)
            self.__previewAxes.set_ylim(0, 30)
            self.__previewAxes.set_xlim(-0.2, 2)
            plt.ion()
            plt.show()
            self.preview_figs[f'{xl},{yl}'] = [self.__previewFigure, self.__previewAxes]
        if len(xd) == 1:
            self.preview_figs[f'{xl},{yl}'][1].scatter([xd],[yd],label=label)
        else:
            self.preview_figs[f'{xl},{yl}'][1].plot(xd,yd,label=label)
        self.preview_figs[f'{xl},{yl}'][1].legend()
        self.preview_figs[f'{xl},{yl}'][0].canvas.draw()
        self.preview_figs[f'{xl},{yl}'][0].canvas.flush_events()
        time.sleep(1e-4) #pause allows plot to update during series of measurements

    def _jv_sweep(self, vstart, vend, vsteps, light = True):
        """Workhorse function to run a singular JV sweep.

        Parameters
        ----------
        vstart : float
            starting voltage (V)
        vend : float
            ending voltage (V)
        vsteps : int
            number of voltage steps 
        light : bool, optional
            is the light on, by default True
        Returns
        -------
        list : Voltage (V), Current Density (mA/cm2), Current (A), Measured Voltage (V) arrays and the Light Boolean
        """
        # initialize i, vmeas, v
        v = np.linspace(vstart, vend, vsteps)
        vmeas = np.zeros((vsteps,))
        i = np.zeros((vsteps,))
        # set scan
        self._source_voltage_measure_current()
        self.keithley.source_voltage = vstart
        self.keithley.enable_source()
        for m, v_ in enumerate(v):
            self.keithley.source_voltage = v_
            vmeas[m], i[m], _ = self.measure()
        self.keithley.disable_source()
        return v, i, vmeas, light
    def _format_jv(self, v, i, vmeas, light, name, dir, scan_number, preview = True):
        """Uses output of `_jv_sweep` along with crucial info to preview and save JV data.

        Parameters
        ----------
        v : np.ndarray(float)
            voltage setpoint array
        i : np.ndarray(float)
            current array
        vmeas : np.ndarray(float)
            voltage PV array
        light : bool
            is the light on
        name : str
            device name
        dir : str
            'fwd' or 'rev' scan
        scan_number : int
            suffix for multiple scans in a row
        preview : bool, optional
            plot results?, by default True
        """
        j = []
        for value in i:
            j.append(-value*1000/self.area) # amps to mA/cm2. sign flip for solar cell current convention
        p = [num1*num2 for num1, num2 in zip(j, vmeas)]
        data = pd.DataFrame({
            "Voltage (V)": v,
            "Current Density (mA/cm2)": j,
            "Measured Voltage (V)": vmeas,
            "Current (A)": i,
            "Power Density (mW/cm2)": p,
        })
        if light:
            light_on_off = "light"
        else:
            light_on_off = "dark"
        if scan_number is None:
            scan_n = ""
        else:
            scan_n = f"_{scan_number}"
        data.to_csv(f"{name}{scan_n}_{dir}_{light_on_off}.csv")
        if preview:
            self._preview(v, j,'Voltage (V)','Current Density (mA/cm2)', f'{name}{scan_n}_{dir}_{light_on_off}')
        
    def _format_spo(self, v, i, vmeas, t, name, preview = True):
        j = []
        for value in i:
            j.append(-value*1000/self.area) # amps to mA/cm2. sign flip for solar cell current convention
        p = [num1*num2 for num1, num2 in zip(j, vmeas)]
        data = pd.DataFrame({
            "Voltage (V)": v,
            "Current Density (mA/cm2)": j,
            "Measured Voltage (V)": vmeas,
            "Current (A)": i,
            "Power Density (mW/cm2)": p,
            "Time Elasped (s)": t,
        })
        data.to_csv(f'{name}_SPO.csv', sep=',')
        if preview:
            self._preview(t, p,'Time (s)', 'Power (mW/cm2)', f'{name}_SPO')
        return data
    def jsc(self, printed = True) -> float:
        """Conducts a short circuit current density measurement

        Parameters
        ----------
        printed : bool, optional
            should we print to terminal the Jsc result?, by default True

        Returns
        -------
        float
            Short Circuit Current Density (mA/cm2)
        """
        self._source_voltage_measure_current()
        self.keithley.source_voltage = 0
        self.keithley.enable_source()
        isc = -self.measure()[1]
        jsc_val = isc*1000/self.area
        self.keithley.disable_source()
        if printed:
            print(f'Isc: {isc:.3f} A, Jsc: {jsc_val:.2f} mA/cm2')
        return jsc_val
    def voc(self, printed = True) -> float:
        """Conducts an open circuit voltage measurement

        Parameters
        ----------
        printed : bool, optional
            should we print to terminal the Voc result?, by default True

        Returns
        -------
        float
            Open Circuit Voltage (V)
        """
        self._source_current_measure_voltage()
        self.source_current = 0
        self.keithley.enable_source()
        voc_val = self._measure()[0]
        self.keithley.disable_source()
        if printed:
            print(f"Voc: {voc_val*1000:.2f} mV")
        return voc_val
    def jv(self, name, direction, vmin, vmax, vsteps = 50, light = True, preview = True):
        """Conducts a JV scan, previews data, saves file

        Parameters
        ----------
        name : str
            name of device
        direction : str
            direction of the scan(s). One of 'fwd', 'rev', 'fwdrev', 'revfwd'
        vmin : float
            starting voltage (V)
        vmax : float
            ending voltage (V)
        vsteps : int, optional
            how many voltage setpoints during the JV sweep, by default 50
        light : bool, optional
            is the light on? by default True
        preview : bool, optional
            do we plot data?, by default True
        """
        # fwd is low v -> high v, reverse is the opposite
        if abs(vmin) < abs(vmax):
            v0 = vmin
            v1 = vmax
        elif abs(vmin) > abs(vmax):
            v0 = vmax
            v1 = vmin
        # separate on call using _jv_sweep and _format_jv functions for light and dark
        if light:
            if (direction == "fwd"):
                v, i, vmeas, light = self._jv_sweep(vstart = v0, vend = v1, vsteps = vsteps, light = True)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='fwd', scan_number=None, preview=preview)
            elif (direction == 'rev'):
                v, i, vmeas, light = self._jv_sweep(vstart = v1, vend = v0, vsteps = vsteps, light = True)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='rev', scan_number=None, preview = preview)
            elif (direction == 'fwdrev'):
                v, i, vmeas, light = self._jv_sweep(vstart = v0, vend = v1, vsteps = vsteps, light = True)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='fwd', scan_number=None, preview = preview)
                v, i, vmeas, light = self._jv_sweep(vstart = v1, vend = v0, vsteps = vsteps, light = True)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='rev', scan_number=None, preview = preview)
            elif (direction == 'revfwd'):
                v, i, vmeas, light = self._jv_sweep(vstart = v1, vend = v0, vsteps = vsteps, light = True)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='rev', scan_number=None, preview = preview)
                v, i, vmeas, light = self._jv_sweep(vstart = v0, vend = v1, vsteps = vsteps, light = True)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='fwd', scan_number=None, preview = preview)
        if not light:
            if (direction == 'fwd'):
                v, i, vmeas, light = self._jv_sweep(vstart = v0, vend = v1, vsteps = vsteps, light = False)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='fwd', scan_number=None, preview = preview)
            elif (direction == 'rev'):
                v, i, vmeas, light = self._jv_sweep(vstart = v1, vend = v0, vsteps = vsteps, light = False)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='rev', scan_number=None, preview = preview)
            elif (direction == 'fwdrev'):
                v, i, vmeas, light = self._jv_sweep(vstart = v0, vend = v1, vsteps = vsteps, light = False)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='fwd', scan_number=None, preview = preview)
                v, i, vmeas, light = self._jv_sweep(vstart = v1, vend = v0, vsteps = vsteps, light = False)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='rev', scan_number=None, preview = preview)
            elif (direction == 'revfwd'):
                v, i, vmeas, light = self._jv_sweep(vstart = v1, vend = v0, vsteps = vsteps, light = False)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='rev', scan_number=None, preview = preview)
                v, i, vmeas, light = self._jv_sweep(vstart = v0, vend = v1, vsteps = vsteps, light = False)
                data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='fwd', scan_number=None, preview = preview)
    def spo(self, name, vstart, vstep, vdelay, interval, interval_count, preview = True):
        """Run a Stable Power Output (SPO) test.

        Parameters
        ----------
        name : str
            name of device/file
        vstart : float
            starting voltage SPO (V)
        vstep : float
            voltage to interate SPO by (V)
        vdelay : float
            time to wait between setting voltage and measuring current (s)
        interval : float
            time between measurements (s)
        interval_count : int
            number of times to repeat interval
        preview : bool, optional
            do we plot data?, by default True
        """
        # setup for MPP tracking
        v = [] # positive
        vmeas = [] # positive
        i = [] # negative
        t = [] # time
        # prep keithley config
        self._source_voltage_measure_current()
        self.keithley.source_voltage = 0
        self.keithley.enable_source()
        vapplied = vstart
        stime = time.time()
        ctime = time.time() - stime
        n = 0
        # make two measurements, iterating voltage in + direction
        while ctime < interval*2:
            # if we aren't at the next time, sleep; else run
            if (ctime <= n*interval):
                time.sleep(1e-3)
            else:
                self.keithley.source_voltage = vapplied
                time.sleep(vdelay)
                tempv, tempi, _ = self._measure()
                vmeas.append(tempv)
                v.append(vapplied)
                i.append(-1*tempi)
                t.append(ctime)
                print(vapplied,tempv,tempi,v)
                n+=1
                vapplied+=vstep
            ctime = time.time() - stime
        # until we have passed the interval
        while ctime < interval*(interval_count):
            if ctime < interval*n:
                time.sleep(1e-3)
            else:
                # calc last powers
                p0 = vmeas[-2]*i[-2]
                p1 = vmeas[-1]*i[-1]
                # iterate in appropriate direction
                if p1 <= p0: # p dec
                    if v[-1] < v[-2]: # v dec
                        vapplied += vstep
                    else:
                        vapplied -= vstep
                else: # p inc
                    if v[-1] > v[-2]: # v dec
                        vapplied += vstep
                    else:
                        vapplied -= vstep
                # apply voltage, measure current and voltage
                self.keithley.source_voltage = vapplied
                time.sleep(vdelay)
                tempv, tempi, _ = self._measure()
                # update dictionary & arrays
                vmeas.append(tempv)
                v.append(vapplied)
                i.append(-1*tempi)
                t.append(ctime)
                print(f'Vapplied: {1000*vapplied:.01f}mV, PCE: {-1000*vapplied*tempi/self.area:0.2f}%')
                n += 1
            ctime = time.time() - stime
        # shutoff keithley
        self.keithley.disable_source()
        # save data
        data = self._format_spo(v=v, i=i, t=t, vmeas=vmeas, name=name, preview=preview)
    # def jsc_time(self,name)
    # def voc_time
    # def jv_rate
    # def jv_spo
