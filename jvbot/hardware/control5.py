from pymeasure.instruments.keithley import Keithley2400
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import time
import csv
import time
from tqdm import tqdm

#################################################
# THIS IS EXPERIMENTAL CODE FOR SCAN RATE and DARK JVs #
#################################################
class Control_Keithley_Eric:
	def __init__(self, area = 0.048, address='GPIB0::22::INSTR'):
		"""
			Initializes Keithley 2400 class SMUs
		"""
		self.area = area
		self.pause = 0.001
		self.wires = 4
		self.compliance_current = 1.05 #2 #1.05 # 1.05 # A
		self.compliance_voltage = 20 #80 #2 # V
		# self.buffer_points = 1
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
		"""
			Prints useful information to terminal
		"""
		output = "Variables\n"
		output += f"self.area = {self.area}\n"
		output += f"self.wires = {self.wires}\n"
		output += f"self.compliance_current = {self.compliance_current}\n"
		output += f"self.compliance_voltage = {self.compliance_voltage}\n"
		print(output)

	def connect(self, keithley_address):
		"""
			Connects to the GPIB interface
		"""
		self.keithley = Keithley2400(keithley_address)
		self.keithley.reset()
		self.keithley.use_front_terminals()
		self.keithley.apply_voltage()
		self.keithley.wires = self.wires
		self.keithley.compliance_current = self.compliance_current
		# self.keithley.buffer_points = self.buffer_points
		# self.keithley.disable_buffer()
		self.keithley.source_voltage = 0

	def disconnect(self):
		"""
			Disconnects from the GPIB interface
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
		"""
			Sets up sourcing current and measuring current
		"""
		self.keithley.voltage_nplc = NPLC
		self.keithley.apply_current()
		self.keithley.measure_voltage()
		self.keithley.source_delay = 0
		self.keithley.source_delay_auto = False
		self.keithley.sample_continuously()
		self.keithley.compliance_voltage = self.compliance_voltage
		self.keithley.source_current = 0

	def _measure(self):

		# self.keithley.config_buffer(self.counts)
		# self.keithley.start_buffer()
		# self.keithley.wait_for_buffer()
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
		# vmeas = np.zeros((vsteps,))
		i = np.zeros((vsteps,))
		i_std = np.zeros((vsteps,))
		v_delay = np.zeros((vsteps,))
		measure_duration_ = np.zeros((vsteps,))
		step_duration = np.zeros((vsteps,))
		self._source_voltage_measure_current(NPLC)
		self.keithley.source_voltage = vstart
		self.keithley.enable_source()

		begin_time = time.time()
		t0 = time.time()
		for m, v_ in enumerate(v):
			if m > 0:
				t0 = time.time()
			i[m], i_std[m], v_delay[m], measure_duration_[m] = self._execute_step(v_, source_delay, measure_duration)
			step_duration[m] = time.time() - t0
		
		end_time = time.time()
		times = end_time-begin_time
		self.keithley.disable_source()
		# reset to defaults:
		self.keithley.current_nplc = self._current_nplc
		self.keithley.source_delay = self._source_delay
		self.keithley.source_delay_auto = self._source_delay_auto

		return v, i, i_std, v_delay, measure_duration_, step_duration, light, times

	def _format_jv(self, v, i, i_std, v_delay, measure_duration, step_duration, times, name, light_on_off = True, dir = "fwd", scan_number = "S1", scan_speed = "M", source_delay = None, preview = True):
		"""
		    Uses output of _jv_sweep along with crucial info to preview and save JV data

			Args:
				v (np.ndarray(float)): voltage array (output from _jv_sweep)
				i (np.ndarray(float)): current array (output from _jv_sweep)
				i_std (np.ndarray(float)): standard deviation of current measurements per voltage step (output from _jv_sweep)
				v_delay (np.ndarray(float)): Duration of settlement time after applying the fresh voltage step to the cell (output from _jv_sweep)
				measure_duration (np.ndarray(float)): Duration of measurement period after settlement time finishes (output from _jv_sweep)
				step_duration (np.ndarray(float)): Full duration of each voltage step (output from _jv_sweep)
				light_on_off (boolean): For file name generation, is the lamp on?
				dir (str): For file name generation, was this a Fwd or Rev scan?
				scan_number (boolean): For file name generation, which repeat scan is this?
				scan_speed (boolean): For file name generation, are we speedy, average, or leisurely? (~V/s)
				source_delay (number): For file name generation, what source_delay/current settlement duration did this scan plan to use?
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


	def jv(self, name, direction, scan_number, vmin, vmax, vsteps = 50, speed_opt = 'M', source_delay = None, measure_duration = None, light = True, pause=False, preview = True):

		if len(direction) == 3:
			dir_0 = direction; skip_dir_1 = True
		else:
			dir_0 = direction[:3]; skip_dir_1 = False; dir_1 = direction[3:]

		if abs(vmin) < abs(vmax):
			v0 = vmin
			v1 = vmax
		elif abs(vmin) > abs(vmax):
			v0 = vmax
			v1 = vmin
		# fwd is from low -> high V, reverse is opposite
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
		"""
			Conducts a short circut current density measurement
			
			Args:
				printed (boolean = True): boolean to determine if jsc is printed
			
			Returns:
				float: Short Circut Current Density (mA/cm2)
		"""
		self._source_voltage_measure_current()
		self.keithley.source_voltage = 0
		self.keithley.enable_source()
		# self.open_shutter()
		isc = -float(self._measure())
		jsc_val = isc*1000/self.area
		# self.close_shutter()
		self.keithley.disable_source()
		if printed:
			print(f'Isc: {isc:.3f} A, Jsc: {jsc_val:.2f} mA/cm2')
		return jsc_val


	def voc(self, printed = True) -> float:
		"""
			Conduct a Voc measurement
			
			Args:
				printed (boolean = True): boolean to determine if voc is printed 
			
			Returns:
				float: Open circut voltage (V)
		"""
		self._source_current_measure_voltage()
		self.souce_current = 0
		self.keithley.enable_source()
		# self.open_shutter()
		voc_val = float(self._measure())
		# self.close_shutter()
		self.keithley.disable_source()
		if printed:
			print(f'Voc: {voc_val*1000:.2f} mV')
		return voc_val

	def jv_time(self, name, scan_num, vstart, vend, vsteps, NPLC, step_duration, source_delay):

		# data_df = pd.DataFrame
		ts = []
		# tts = []
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
		self.keithley.enable_source()
		t0 = time.time()
		print('Starting JV Sweep.')
		for m, v_ in enumerate(v):
			print(f"\tExecuting step {m+1}/{len(v)} now.")
			self.keithley.source_voltage = v_
			t_step_0 = time.time()
			j_step = []
			v_step = []
			t_step = []
			# t_total = []
			while time.time() - t_step_0 <= step_duration:
				j_ = -1000*float(self._measure())/self.area
				j_step.append(j_)
				v_step.append(v_)
				t_step.append(time.time() - t_step_0)
				j_total.append(j_)
				v_total.append(v_)
				t_total.append(time.time() - t0)
			# tts.append(t_total)
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
			print(f'Working on direction set {d_idx+1}/{len(directions)}')
			if len(direction) == 3:
				dir_0 = direction; skip_dir_1 = True
			else:
				dir_0 = direction[:3]; skip_dir_1 = False; dir_1 = direction[3:]
			
			if abs(vstart) < abs(vend):
				v0 = vstart
				v1 = vend
			elif abs(vstart) > abs(vend):
				v0 = vend
				v1 = vstart
			# fwd is from low -> high V, reverse is opposite
			if 'f' in dir_0:
				vstart_0 = v0; vend_0 = v1
				vstart_1 = v1; vend_1 = v0
			else:
				vstart_0 = v0; vend_0 = v1
				vstart_1 = v1; vend_1 = v0
			for s_idx, scan_rate in enumerate(scan_rates):
				print(f'\tWorking on scan_rate {s_idx+1}/{len(scan_rates)} now.')
				vstep_size = abs(vend - vstart) / (vsteps - 1)
				# rate = V/s
				# s = source_delay + measurement_duration
				# hold measurement_duration at 5 seconds
				if delay_measure_split is None:
					source_delay = vstep_size/scan_rate - measurement_duration
				else:
					# source_delay*delay_measure_split = measure_duration
					# vstep_size/scan_rate = source_delay*(1 + delay_measure_split)
					source_delay = (vstep_size/scan_rate)/(1 + delay_measure_split)
					measurement_duration = source_delay*delay_measure_split
					if delay_measure_split != measurement_duration / source_delay:
						raise Exception("The math is wrong here.")
				# source_delay = vstep_size/scan_rate - measurement_duration
				# print(scan_rate, source_delay)
				for s_idx, sn in enumerate(np.arange(repeat_scans)):
					print(f'\t\tExecuting repeat scan {s_idx+1}/{len(np.arange(repeat_scans))}')
					scan_n = f"S{sn+1}"
					v, i, i_std, v_delay, measure_duration_, step_duration, light, times = self._jv_sweep(vstart = vstart_0, vend = vend_0, vsteps = vsteps, source_delay = source_delay, measure_duration = measurement_duration, NPLC = NPLC, light = light)
					data = self._format_jv(v = v, i = i, i_std = i_std, v_delay = v_delay, measure_duration = measure_duration_, step_duration = step_duration, times = times, name = name, light_on_off = light, dir = dir_0, scan_number = scan_n, scan_speed = scan_rate, source_delay = source_delay, preview = True)
					if not skip_dir_1:
						v, i, i_std, v_delay, measure_duration_, step_duration, light, times = self._jv_sweep(vstart = vstart_1, vend = vend_1, vsteps = vsteps, source_delay = source_delay, measure_duration = measurement_duration, NPLC = NPLC, light = light)
						data = self._format_jv(v = v, i = i, i_std = i_std, v_delay = v_delay, measure_duration = measure_duration_, step_duration = step_duration, times = times, name = name, light_on_off = light, dir = dir_1, scan_number = scan_n, scan_speed = scan_rate, source_delay = source_delay, preview = True)

	def dark_jv(
		self, 
		slot,
		current_stability_threshold, #0-100 %
		fit_windows, # seconds
		repeat_scans,
		vstart, 
		vend, 
		vsteps, 
		directions, 
		NPLC = 1, 
		n_measurements = 15,
		crash_time = int(15*60), # 15 minutes 
		dark = True,
		preview = True):
		R_thresh = current_stability_threshold
		for d_idx, direction in enumerate(directions):
			print(f'Working on direction set {d_idx+1}/{len(directions)}')
			if len(direction) == 3:
				dir_0 = direction; skip_dir_1 = True
			else:
				dir_0 = direction[:3]; skip_dir_1 = False; dir_1 = direction[3:]
			
			if abs(vstart) < abs(vend):
				v0 = vstart
				v1 = vend
			elif abs(vstart) > abs(vend):
				v0 = vend
				v1 = vstart
			# fwd is from low -> high V, reverse is opposite
			if 'f' in dir_0:
				vstart_0 = v0; vend_0 = v1
				vstart_1 = v1; vend_1 = v0
			else:
				vstart_0 = v0; vend_0 = v1
				vstart_1 = v1; vend_1 = v0
			v_0 = np.linspace(vstart_0, vend_0, vsteps)
			v_1 = np.linspace(vstart_1, vend_1, vsteps)
			
			for f_idx, fit_window in enumerate(fit_windows):
				print(f'\tWorking on fit_window {f_idx+1}/{len(fit_windows)}')
				for s_idx, sn in enumerate(np.arange(repeat_scans)):
					print(f'\t\tWorking on scan_rate {s_idx+1}/{repeat_scans} now.')
					# execute direction_0 sweep
					I_meas = []
					I_std = []
					V_app = []
					self._source_voltage_measure_current(NPLC)
					self.keithley.source_voltage = vstart_0
					self.keithley.enable_source()
					t_begin = time.time()
					for v_ in v_0:
						R = 100
						if v_ != vstart_0:
							self.keithley.source_voltage = v_
						print(f"\t\t\tSearching for Stable Current Now. with fit_window: {fit_window} s")
						print(R, R_thresh)
						while R >= R_thresh:
							I_obs = []
							t_obs = []
							tbin_0 = time.time()
							tnow = time.time() - tbin_0
							# print(tnow)
							while tnow <= fit_window:
								I_obs.append(float(self._measure()))
								tnow = time.time() - tbin_0
								t_obs.append(tnow)
								# print(tnow)
							s, _ = np.polyfit(t_obs, I_obs, 1)
							I_mean = np.mean(I_obs)
							R = abs(s/I_mean)*100 # %
							print(f"\t\t\tV: {v_}, R: {R}, duration: {tnow}")
							# print(len(I_obs), len(t_obs), tnow - tbin_0, "R: {R}")
							if tnow - t_begin > crash_time:
								self.keithley.disable_source()
								self.keithley.current_nplc = self._current_nplc
								self.keithley.source_delay = self._source_delay
								self.keithley.source_delay_auto = self._source_delay_auto
								raise Exception('Scan took too long, so it was cutoff.')
						I_vals = []
						while len(I_vals) <= n_measurements:
							I_vals.append(float(self._measure()))
						I_meas.append(np.mean(I_vals))
						I_std.append(np.std(I_vals))
						V_app.append(v_)
					self.keithley.disable_source()
					J_meas = [-i*1000/self.area for i in I_meas]
					J_std = [-i*1000/self.area for i in I_std]
					P = [j_*v_ for j_, v_ in zip(J_meas, V_app)]
					# dump results:
					data = pd.DataFrame(
						{
							"Voltage (V)": V_app,
							"Current Density (mA/cm2)": J_meas,
							"Current (A)": I_meas,
							"Power Density (mW/cms)": P
						}
					)
					light_on_off = "dark"
					scan_n = f"_S{sn}"
					fw_str = str(fit_window)
					if '.' in fw_str:
						fw_0, fw_1 = fw_str.split('.')
					else:
						fw_0 = fw_str; fw_1 = '0'
					fw = f"_FW{fw_0}-{fw_1}"
					rt_str = str(R_thresh)
					if '.' in rt_str:
						rt_0, rt_1 = rt_str.split('.')
					else:
						rt_0 = rt_str; rt_1 = '0'
					rt = f"_RT{rt_0}-{rt_1}"
					filename = f"{slot}{scan_n}_{dir_0}{fw}{rt}_{light_on_off}.csv"
					data.to_csv(filename)
					# update figure:
					if preview:
						self._preview(V_app, [-j_ for j_ in J_meas], 'Voltage (V)', 'Current Density (mA/cm2)', f"{slot}{scan_n}_{dir_0}{fw}{rt}_{light_on_off}", dark = True)
					if not skip_dir_1:
						# execute direction_1 sweep
						I_meas = []
						I_std = []
						V_app = []
						# self._source_voltage_measure_current(NPLC)
						self.keithley.source_voltage = vstart_1
						self.keithley.enable_source()
						t_begin = time.time()
						for v_ in v_1:
							R = 100
							if v_ != vstart_1:
								self.keithley.source_voltage = v_
							while R >= R_thresh:
								I_obs = []
								t_obs = []
								tbin_0 = time.time()
								tnow = time.time() - tbin_0
								while tnow <= fit_window:
									I_obs.append(float(self._measure()))
									tnow = time.time() - tbin_0
									t_obs.append(tnow)
								# print(len(I_obs), len(t_obs), tnow - tbin_0)
								s, _ = np.polyfit(t_obs, I_obs, 1)
								I_mean = np.mean(I_obs)
								R = abs(s/I_mean)*100 # %
								print(f"\t\t\tV: {v_}, R: {R}, duration: {tnow}")
								if tnow - t_begin > crash_time:
									self.keithley.disable_source()
									self.keithley.current_nplc = self._current_nplc
									self.keithley.source_delay = self._source_delay
									self.keithley.source_delay_auto = self._source_delay_auto
									raise Exception('Scan took too long, so it was cutoff.')


							I_vals = []
							while len(I_vals) <= n_measurements:
								I_vals.append(float(self._measure()))
							I_meas.append(np.mean(I_vals))
							I_std.append(np.std(I_vals))
							V_app.append(v_)
						self.keithley.disable_source()
						# dump results:
						J_meas = [-i*1000/self.area for i in I_meas]
						J_std = [-i*1000/self.area for i in I_std]
						P = [j_*v_ for j_, v_ in zip(J_meas, V_app)]
						# dump results:
						data = pd.DataFrame(
							{
								"Voltage (V)": V_app,
								"Current Density (mA/cm2)": J_meas,
								"Current (A)": I_meas,
								"Power Density (mW/cms)": P
							}
						)
						light_on_off = "dark"
						scan_n = f"_S{sn}"
						fw_str = str(fit_window)
						if '.' in fw_str:
							fw_0, fw_1 = fw_str.split('.')
						else:
							fw_0 = fw_str; fw_1 = '0'
						fw = f"_FW{fw_0}-{fw_1}"
						rt_str = str(R_thresh)
						if '.' in rt_str:
							rt_0, rt_1 = rt_str.split('.')
						else:
							rt_0 = rt_str; rt_1 = '0'
						rt = f"_RT{rt_0}-{rt_1}"
						filename = f"{slot}{scan_n}_{dir_1}{fw}{rt}_{light_on_off}.csv"
						data.to_csv(filename)
						# update figure:
						if preview:
							self._preview(V_app, [-j_ for j_ in J_meas], 'Voltage (V)', 'Current Density (mA/cm2)', f"{slot}{scan_n}_{dir_1}{fw}{rt}_{light_on_off}", dark = True)
		print('Finished!')			
		# reset to defaults:
		self.keithley.current_nplc = self._current_nplc
		self.keithley.source_delay = self._source_delay
		self.keithley.source_delay_auto = self._source_delay_auto

	def _sweep_dark_jv_slope(self, v_array, NPLC, R_thresh, fit_window, n_measurements, crash_time, measure_delay = 0):
		# execute direction_0 sweep
		I_meas = []
		I_std = []
		V_app = []
		self._source_voltage_measure_current(NPLC)
		self.keithley.source_voltage = v_array[0]
		self.keithley.enable_source()
		t_begin = time.time()
		for v_ in v_array:
			R = 100
			if v_ != v_array[0]:
				self.keithley.source_voltage = v_
			print(f"\t\t\tSearching for Stable Current Now. with fit_window: {fit_window} s")
			print(R, R_thresh)
			while R >= R_thresh:
				I_obs = []
				t_obs = []
				tbin_0 = time.time()
				tnow = time.time() - tbin_0
				# print(tnow)
				while tnow <= fit_window:
					I_obs.append(float(self._measure()))
					tnow = time.time() - tbin_0
					t_obs.append(tnow)
					time.sleep(measure_delay)
					# print(tnow)
				s, _ = np.polyfit(t_obs, I_obs, 1)
				I_mean = np.mean(I_obs)
				R = abs(s/I_mean)*100 # %
				print(f"\t\t\tV: {v_}, R: {R}, duration: {tnow}")
				# print(len(I_obs), len(t_obs), tnow - tbin_0, "R: {R}")
				if tnow - t_begin > crash_time:
					self.keithley.disable_source()
					self.keithley.current_nplc = self._current_nplc
					self.keithley.source_delay = self._source_delay
					self.keithley.source_delay_auto = self._source_delay_auto
					raise Exception('Scan took too long, so it was cutoff.')
			I_vals = []
			while len(I_vals) <= n_measurements:
				I_vals.append(float(self._measure()))
			I_meas.append(np.mean(I_vals))
			I_std.append(np.std(I_vals))
			V_app.append(v_)
		self.keithley.disable_source()
		self._reset_keithley()
		return I_meas, I_std, V_app

	def _sweep_dark_jv_bins(self, v_array, NPLC, R_thresh, fit_bin, n_measurements, crash_time, measure_delay, verbose = True):
		# execute direction_0 sweep
		I_meas = []
		I_std = []
		V_app = []
		self._source_voltage_measure_current(NPLC)
		self.keithley.source_voltage = v_array[0]
		self.keithley.enable_source()
		t_begin = time.time()
		for v_ in v_array:
			R = 100
			if v_ != v_array[0]:
				self.keithley.source_voltage = v_
			if verbose:
				print(f"\t\t\tSearching for Stable Current Now. with fit_bin: {fit_bin} samples")
				print(R, R_thresh)
			prev_I_mean = 1e3
			t_begin = time.time()
			rbar = tqdm("Stabilizing")
			w = 0
			while R >= R_thresh:
				I_obs = []
				# t_obs = []
				tbin_0 = time.time()
				# tnow = time.time() - tbin_0
				# print(tnow)
				while len(I_obs) <= fit_bin:
					I_obs.append(float(self._measure()))
					tnow = time.time() - tbin_0
					time.sleep(measure_delay) # measure current roughly twice per second.
					# t_obs.append(tnow)
					# print(tnow)
				# s, _ = np.polyfit(t_obs, I_obs, 1)
				I_mean = np.mean(I_obs)
				
				R = abs((prev_I_mean - I_mean)/((prev_I_mean + I_mean)/2))*100 # %
				prev_I_mean = I_mean
				rbar.update(w)
				w += 1
				if verbose:
					print(f"\t\t\tV: {v_}, R: {R}, duration: {tnow}")
				# print(len(I_obs), len(t_obs), tnow - tbin_0, "R: {R}")
				if tnow - t_begin > crash_time:
					self.keithley.disable_source()
					self.keithley.current_nplc = self._current_nplc
					self.keithley.source_delay = self._source_delay
					self.keithley.source_delay_auto = self._source_delay_auto
					print('\t\t\t\tScan took too long to stabilize, moving on with life.')
					# raise Exception('Scan took too long, so it was cutoff.')
			rbar.close()
			I_vals = []
			while len(I_vals) <= n_measurements:
				I_vals.append(float(self._measure()))
			I_meas.append(np.mean(I_vals))
			I_std.append(np.std(I_vals))
			V_app.append(v_)
		self.keithley.disable_source()
		self._reset_keithley()
		return I_meas, I_std, V_app

					
		
	def _reset_keithley(self):
		self.keithley.current_nplc = self._current_nplc
		self.keithley.source_delay = self._source_delay
		self.keithley.source_delay_auto = self._source_delay_auto

	def _execute_voltage_sweep(self, v_array, stable_method = 'slope', **kwargs):
		if stable_method not in ['slope', 'bin']:
			raise Exception("The `stable_method` input must be in ['slope', 'bin']")
		R_thresh = kwargs.get('R_thresh', 0.02)
		if stable_method == 'slope':
			fit_window = kwargs.get('fit_window', 30)
			I_meas, I_std, V_app = self._sweep_dark_jv_slope(v_array = v_array, NPLC = kwargs.get('NPLC', 1), fit_window = fit_window,
			R_thresh = R_thresh, n_measurements = kwargs.get('n_measurements', 30), crash_time = kwargs.get('crash_time', int(30*60)),
			measure_delay = kwargs.get('measure_delay', 0))
			self._format_dark_jv(I_array = I_meas, I_stddev = I_std, v_array = V_app, stable_method = 'slope', 
			scan_number = kwargs.get('scan_number', 1), R_thresh = R_thresh, preview = True,
			slot = kwargs.get('slot', 'A1'), dir = kwargs.get('dir', 'fwd'))
		if stable_method == 'bin':
			fit_bin = kwargs.get('fit_window', 50)
			I_meas, I_std, V_app = self._sweep_dark_jv_bins(v_array = v_array, NPLC = kwargs.get('NPLC', 1), fit_bin = fit_bin,
			R_thresh = R_thresh, n_measurements = kwargs.get('n_measurements', 30), crash_time = kwargs.get('crash_time', int(30*60)),
			measure_delay = kwargs.get('measure_delay', 0))
			self._format_dark_jv(I_array = I_meas, I_stddev = I_std, v_array = V_app, stable_method = 'slope', 
			scan_number = kwargs.get('scan_number', 1), R_thresh = R_thresh, preview = True,
			slot = kwargs.get('slot', 'A1'), dir = kwargs.get('dir', 'fwd'))
		return I_meas, I_std, V_app
	def _format_dark_jv(
		self, 
		I_array, 
		I_stddev, 
		v_array, 
		slot = "A1",
		dir = "fwd",
		stable_method = 'slope',
		scan_number = 1,
		R_thresh = 0.02,
		fit_window = None,
		fit_bin = None,
		preview = True):
		J_meas = [-i*1000/self.area for i in I_array]
		J_std = [-i*1000/self.area for i in I_stddev]
		P = [j_*v_ for j_, v_ in zip(J_meas, v_array)]
		# dump results:
		data = pd.DataFrame(
			{
				"Voltage (V)": v_array,
				"Current Density (mA/cm2)": J_meas,
				"Current (A)": I_array,
				"Current Standard Deviation (A)": I_stddev,
				"Current Density Standard Deviation (mA/cm2)": J_std,
				"Power Density (mW/cms)": P
			}
		)
		light_on_off = "dark"
		scan_n = f"_S{scan_number}"
		if stable_method == 'slope':
			fw_str = str(fit_window)
			if '.' in fw_str:
				fw_0, fw_1 = fw_str.split('.')
			else:
				fw_0 = fw_str; fw_1 = '0'
			fw = f"_FW{fw_0}-{fw_1}"
			fb = ""
		if stable_method == 'bin':
			fb_str = str(fit_bin)
			if '.' in fb_str:
				fb_0, fb_1 = fb_str.split('.')
			else:
				fb_0 = fb_str; fb_1 = '0'
			fb = f"_FB{fb_0}-{fb_1}"
			fw = ""
		rt_str = str(R_thresh)
		if '.' in rt_str:
			rt_0, rt_1 = rt_str.split('.')
		else:
			rt_0 = rt_str; rt_1 = '0'
		rt = f"_RT{rt_0}-{rt_1}"
		filename = f"{slot}{scan_n}_{dir}{fw}{fb}{rt}_{light_on_off}.csv"
		data.to_csv(filename)
		# update figure:
		if preview:
			self._preview(v_array, [-j_ for j_ in J_meas], 'Voltage (V)', 'Current Density (mA/cm2)', f"{slot}{scan_n}_{dir}{fw}{fb}{rt}_{light_on_off}", dark = True)

	def dark_jv_v2(
		self, 
		slot,
		current_stability_threshold, #0-100 %
		repeat_scans,
		vstart, 
		vend, 
		vsteps, 
		directions, 
		fit_windows = None, # seconds
		fit_bins = None, # how many current values to bin for stable method bin
		stable_method = 'slope',
		NPLC = 1, 
		n_measurements = 15,
		crash_time = int(15*60), # 15 minutes 
		measure_delay = 0,
		dark = True,
		preview = True,
		verbose = False):

		if stable_method == 'slope':
			try:
				fit_windows = fit_windows
				if fit_windows is None:
					fit_windows = [30]
			except:
				fit_windows = [30]
		if stable_method == 'bin':
			try:
				fit_windows = fit_bins
				if fit_windows is None:
					fit_windows = [50]
			except:
				fit_windows = [50]
		
		R_thresh = current_stability_threshold
		for d_idx, direction in enumerate(directions):
			if verbose:
				print(f'Working on direction set {d_idx+1}/{len(directions)}')
			if len(direction) == 3:
				dir_0 = direction; skip_dir_1 = True
			else:
				dir_0 = direction[:3]; skip_dir_1 = False; dir_1 = direction[3:]
			
			if abs(vstart) < abs(vend):
				v0 = vstart
				v1 = vend
			elif abs(vstart) > abs(vend):
				v0 = vend
				v1 = vstart
			# fwd is from low -> high V, reverse is opposite
			if 'f' in dir_0:
				vstart_0 = v0; vend_0 = v1
				vstart_1 = v1; vend_1 = v0
			else:
				vstart_0 = v0; vend_0 = v1
				vstart_1 = v1; vend_1 = v0
			v_0 = np.linspace(vstart_0, vend_0, vsteps)
			v_1 = np.linspace(vstart_1, vend_1, vsteps)
			
			for f_idx, fit_window in enumerate(fit_windows):
				if verbose:
					print(f'\tWorking on fit_window {f_idx+1}/{len(fit_windows)}')
				for s_idx, sn in enumerate(np.arange(repeat_scans)):
					if verbose:
						print(f'\t\tWorking on scan_rate {s_idx+1}/{repeat_scans} now.')
					I_meas, I_std, V_app = self._execute_voltage_sweep(v_array = v_0, stable_method = stable_method,
					scan_number = int(sn+1), n_measurements = n_measurements, R_thresh = R_thresh, slot = slot, dir = dir_0,
					NPLC = NPLC, crash_time = crash_time, measure_delay = measure_delay)
					if not skip_dir_1:
						I_meas, I_std, V_app = self._execute_voltage_sweep(v_array = v_1, stable_method = stable_method,
						scan_number = int(sn+1), n_measurements = n_measurements, R_thresh = R_thresh, slot = slot, dir = dir_0,
						NPLC = NPLC, crash_time = crash_time, measure_delay = measure_delay)
		if verbose:
			print('Finished!')
		self._reset_keithley()
						

				


		



	# def _format_jv(self, v, i, vmeas, light, name, dir, scan_number, preview = True):
	# 	"""
	# 		Uses output of _jv_sweep along with crucial info to preview and save JV data
			
	# 		Args:
	# 			v (np.ndarray(float)): voltage array (output from _sweep_jv)
	# 			i (np.ndarray(float)): current array (output from _sweep_jv)
	# 			vmeas (np.ndarray(float)): measured voltage array (output from _sweep_jv)
	# 			light (boolean = True): boolean to describe status of light
	# 			name (string): name of device
	# 			dir (string): direction -- fwd or rev
	# 			scan_number (int): suffix for multiple scans in a row
	# 			preview (boolean = True): option to preview in graph
	# 	"""
	# 	# calc param
	# 	j = []
	# 	for value in i:
	# 		j.append(-value*1000/self.area) #amps to mA/cm2. sign flip for solar cell current convention)	
	# 	p = [num1*num2 for num1, num2 in zip(j,vmeas)]

	# 	# build dataframe
	# 	data = pd.DataFrame({
	# 		'Voltage (V)': v,
	# 		'Current Density (mA/cm2)': j,
	# 		'Current (A)': i,
	# 		'Measured Voltage (V)': vmeas,
	# 		'Power Density (mW/cm2)': p,
	# 	})
		
	# 	# save csv
	# 	if light:
	# 		light_on_off = "light"
	# 	else:
	# 		light_on_off = "dark"
	# 	if scan_number is None:
	# 		scan_n = ""
	# 	else:
	# 		scan_n = f'_{scan_number}'
	# 	data.to_csv(f'{name}{scan_n}_{dir}_{light_on_off}.csv')

	# 	# preview
	# 	if preview:
	# 		self._preview(v, j,'Voltage (V)','Current Density (mA/cm2)', f'{name}{scan_n}_{dir}_{light_on_off}')
		
	# 	return data


	def _preview(self,xd,yd,xl,yl,label, dark: bool = False):
		"""
			Appends the [xd,yd] arrays to preview window with labels [xl,yl] and trace label label.
			
			Args:
				xd (list): x value
				yd (list): y value
				yl (string): y label
				xl (string): xlabel
				label (string): label for graph
				dark (boolean): True = semilogy plot, False = linear y plot
		"""

		def handle_close(evt, self):
			del self.preview_figs[f'{xl},{yl}']


		if f'{xl},{yl}' not in self.preview_figs.keys():
			plt.ioff()
			self.__previewFigure, self.__previewAxes = plt.subplots()
			self.__previewFigure.canvas.mpl_connect('close_event', lambda x: handle_close(x, self))	# if preview figure is closed, lets clear the figure/axes handles so the next preview properly recreates the handles
			self.__previewAxes.set_xlabel(xl)
			self.__previewAxes.set_ylabel(yl)
			
			self.__previewAxes.set_yscale('log' if dark else 'linear')

			plt.ion()
			plt.show()
			self.preview_figs[f'{xl},{yl}'] = [self.__previewFigure, self.__previewAxes]

		self.__previewAxes.set_yscale('log' if dark else 'linear')


		if len(xd) == 1:
			self.preview_figs[f'{xl},{yl}'][1].scatter([xd],[yd], label = label)
		else:	
			self.preview_figs[f'{xl},{yl}'][1].plot(xd,yd, label = label)
		# if dark:
			# self.preview_figs[f'{xl},{yl}'][1]
		self.preview_figs[f'{xl},{yl}'][1].legend()
		self.preview_figs[f'{xl},{yl}'][0].canvas.draw()
		self.preview_figs[f'{xl},{yl}'][0].canvas.flush_events()
		time.sleep(1e-4)		#pause allows plot to update during series of measurements 
