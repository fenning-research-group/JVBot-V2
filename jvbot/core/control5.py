from pymeasure.instruments.keithley import Keithley2400
import numpy as np
import pandas as pd
class Control_Keithley:
	def __init__(self, area = 0.048, address='GPIB0::22::INSTR'): 
		"""
			Initializes Keithley 2400 class SMUs
		"""
		self.area = area
		self.wires = 4
		self.compliance_current = 1.05 # A
		self.compliance_voltage = 2 # V
		self.buffer_points = 2
		self._scan_speeds = {
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
		self.connect(keithley_address=address)
		self.preview_figs = {}


	def help(self):
		"""
			Prints useful information to terminal
		"""
		output = "Variables\n"
		output += f'self.area = {self.area}\n'
		output += f'self.wires = {self.wires}\n'
		output += f'self.compliance_current = {self.compliance_current}\n'
		output += f'self.compliance_voltage = {self.compliance_voltage}\n'
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
		self.keithley.buffer_points = self.buffer_points
		self.keithley.source_voltage = 0

	def disconnect(self):
		"""
			Disconnects from the GPIB interface
		"""
		self.keithley.shutdown()

	def _source_voltage_measure_current(self):
		"""
			Sets up sourcing voltage and measuring current
		"""
		self.keithley.apply_voltage()
		self.keithley.measure_current()
		self.keithley.compliance_current = self.compliance_current
		self.keithley.souce_voltage = 0


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
	def _jv_sweep(self, vstart, vend, vsteps, light = True):
		""" 
			Workhorse function to run a singular JV sweep.
			
			Args:
				vstart (foat): starting voltage for JV sweep (V)
				vend (float): ending voltage for JV sweep (V)
				vsteps (int): number of voltage steps
				light (boolean = True): boolean to describe light status
			
			Returns:
				list: Voltage (V), Current Density (mA/cm2), Current (A), and Measured Voltage (V) arrays and Light Boolean
		"""
		
		# setup v, vmeas, i
		v = np.linspace(vstart, vend, vsteps)
		vmeas = np.zeros((vsteps,))
		i = np.zeros((vsteps,))
		
		# set scan
		self._source_voltage_measure_current()
		self.keithley.source_voltage = vstart
		self.keithley.enable_source()

		for m, v_ in enumerate(v):
			self.keithley.source_voltage = v_
			vmeas[m], i[m], _ = self._measure()

		self.keithley.disable_source()
		
		# build dataframe and return
		return v, i, vmeas, light


	def _format_jv(self, v, i, vmeas, light, name, dir, scan_number, preview = True):
		"""
			Uses output of _jv_sweep along with crucial info to preview and save JV data
			
			Args:
				v (np.ndarray(float)): voltage array (output from _sweep_jv)
				i (np.ndarray(float)): current array (output from _sweep_jv)
				vmeas (np.ndarray(float)): measured voltage array (output from _sweep_jv)
				light (boolean = True): boolean to describe status of light
				name (string): name of device
				dir (string): direction -- fwd or rev
				scan_number (int): suffix for multiple scans in a row
				preview (boolean = True): option to preview in graph
		"""
		# calc param
		j = []
		for value in i:
			j.append(-value*1000/self.area) #amps to mA/cm2. sign flip for solar cell current convention)	
		p = [num1*num2 for num1, num2 in zip(j,vmeas)]

		# build dataframe
		data = pd.DataFrame({
			'Voltage (V)': v,
			'Current Density (mA/cm2)': j,
			'Current (A)': i,
			'Measured Voltage (V)': vmeas,
			'Power Density (mW/cm2)': p,
		})
		
		# save csv
		if light:
			light_on_off = "light"
		else:
			light_on_off = "dark"
		if scan_number is None:
			scan_n = ""
		else:
			scan_n = f'_{scan_number}'
		data.to_csv(f'{name}{scan_n}_{dir}_{light_on_off}.csv')

		# preview
		if preview:
			self._preview(v, j,'Voltage (V)','Current Density (mA/cm2)', f'{name}{scan_n}_{dir}_{light_on_off}')
		
		return data


	def jv(self, name, direction, vmin, vmax, vsteps = 50, light = True, preview = True):
		"""
			Conducts a JV scan, previews data, saves file
			
			Args:
				name (string): name of device
				direction (string): direction -- fwd, rev, fwdrev, or revfwd
				vmin (float): start voltage for JV sweep (V)
				xmax (float): end voltage for JV sweep (V)
				vsteps (int = 50): number of voltage steps between max and min
				light (boolean = True): boolean to describe status of light
				preview (boolean = True): boolean to determine if data is plotted
		"""

		# fwd is going to be from the lower abs v to higher abs v, reverse will be opposite
		if abs(vmin) < abs(vmax):
			v0 = vmin
			v1 = vmax
		elif abs(vmin) > abs(vmax):
			v0 = vmax
			v1 = vmin

		# seperate on call using _jv_sweep and _format_jv functions for light and dark
		if light:
			if (direction == 'fwd'):
				v, i, vmeas, light = self._jv_sweep(vstart = v0, vend = v1, vsteps = vsteps, light = True)
				data = self._format_jv(v=v, i=i, vmeas=vmeas, light=light, name=name, dir='fwd', scan_number=None, preview = preview)
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
