import os
import yaml
import shutil
import pickle as pkl
from natsort import natsorted
import csv
from datetime import datetime
from tqdm import tqdm
from frgtools import jv

try:
    from typing import Literal
except:
    from typing_extensions import Literal



MODULE_DIR = os.path.dirname(__file__)
TRAY_VERSIONS_DIR = os.path.join(MODULE_DIR, "tray_versions")
AVAILABLE_VERSIONS = {
    os.path.splitext(f)[0]: os.path.join(TRAY_VERSIONS_DIR, f)
    for f in os.listdir(TRAY_VERSIONS_DIR)
    if ".yaml" in f
}

from .hardware.old_gantry import Gantry
from .hardware.light_JV_legacy import Control_Keithley as OldControl
from .hardware.control5 import Control_Keithley as DarkJVScanRatesControl
from .hardware.tray_legacy import Tray

class JVControl:
    def __init__(self, area = 0.048, Eric_Opt = None):
        self.area = area # cm2
        if Eric_Opt is None:
            response = self._prompt_for_input("Do you want to use Eric's Scan-Rate Sweeps or Dark JV's? (y/n)")
            if response in ['y', 'Y']:
                self.control_keithley = DarkJVScanRatesControl(area = self.area, ScanRateDarkJV = True)
            else:
                self.control_keithley = OldControl(area = self.area)
                # ScanRateDarkJV = False)
        self.gantry = Gantry()
    
    def _prompt_for_input(self, s):
        response = input(s)
        return response
    def set_tray(self, version: str, calibrate: bool = False):
        self.gantry.moveto([55, 24, 30])
        self.tray = Tray(version = version, gantry = self.gantry, calibrate = calibrate)
    
    def scan_cell(
            self,
            name: str,
            vmin: float,
            vmax: float,
            direction: Literal['fwd', 'rev', 'fwdrev', 'revfwd'] = 'fwdrev',
            vsteps: int = 50,
            light: bool = True,
            preview: bool = True,
            **kwargs
        ):
        """Conducts a JV scan, previews data, saves file.

        Parameters
        ----------
        name : str
            name of device
        vmin : float
            Starting voltage for JV sweep (V).
        vmax : float
            Ending voltage for JV sweep (V).
        direction : str, optional
            Sweep direction, by default 'fwdrev'.
        vsteps : int, optional
            Number of voltage steps between max and min, by default 50.
        light : bool, optional
            If solar sim light is incident upon device, by default True.
        preview : bool, optional
            If data is plotted after scan., by default True.
        """
        self.control_keithley.jv(
            name = name,
            direction = direction,
            vmin = vmin,
            vmax = vmax,
            vsteps = vsteps,
            light = light,
            preview = preview
        )

    def scan_tray(
            self,
            vmin,
            vmax,
            direction = 'revfwd',
            vsteps = 50,
            repeat_scans=1,
            initial_slot=None,
            final_slot=None,
            slots=None,
            light=True,
            preview=True,
            **kwargs
        ):

        allslots = natsorted(list(self.tray._coordinates.keys()))
        if final_slot == None:
            slots = allslots
        else: # if a final slot is specified
            final_idx = allslots.index(final_slot)
            if initial_slot is not None:
                initial_idx = allslots.index(initial_slot)
                slots = allslots[initial_idx:final_idx+1]
            else:
                slots = allslots[:final_idx+1]

        if slots is None:
            raise ValueError("Either final_slot or slots must be specified!")
        if light:
            for slot in tqdm(slots, desc="Scanning Tray"):
                self.gantry.moveto(self.tray(slot))
                for i in range(repeat_scans):
                    name = f"{slot}_S{i+1}"
                    self.control_keithley.jv(name=name, direction=direction, vmin=vmin, vmax=vmax, vsteps=vsteps, light=light, preview=preview)
        if not light: # take Dark JVs
            repeats = []
            for i in range(repeat_scans):
                repeats.append(f"S{i+1}")
            fit_windows = kwargs.get('fit_window', [50])
            n_measurements = kwargs.get('n_measurements', 15)
            NPLC = kwargs.get('NPLC', 1)
            crash_time = kwargs.get('crash_time', int(15*60))
            current_stability_threshold = kwargs.get('current_stability_threshold', 0.2)
            directions = [direction]
            stable_method = kwargs.get('stable_method', 'bin')
            if stable_method == 'bin':
                for slot in tqdm(slots, desc="Scanning Tray"):
                    self.gantry.moveto(self.tray(slot))
                    self.control_keithley.dark_jv_v2(
                        slot = slot,
                        current_stability_threshold = current_stability_threshold,
                        # repeat_scans = repeats,
                        repeat_scans = repeat_scans,
                        vstart = vmin,
                        vend = vmax,
                        vsteps = vsteps,
                        directions = directions,
                        fit_bins = fit_windows,
                        stable_method = stable_method,
                        NPLC = NPLC,
                        n_measurements = n_measurements,
                        crash_time = crash_time,
                        measure_delay = kwargs.get('measure_delay', 0),
                        dark = True,
                        preview = True,
                        verbose = False,
                    )
            elif stable_method == 'slope':
                for slot in tqdm(slots, desc="Scanning Tray"):
                    self.gantry.moveto(self.tray(slot))
                    self.control_keithley.dark_jv_v2(
                        slot = slot,
                        current_stability_threshold = current_stability_threshold,
                        # repeat_scans = repeats,
                        repeat_scans = repeat_scans,
                        vstart = vmin,
                        vend = vmax,
                        vsteps = vsteps,
                        directions = directions,
                        fit_windows = fit_windows,
                        stable_method = stable_method,
                        NPLC = NPLC,
                        n_measurements = n_measurements,
                        crash_time = crash_time,
                        measure_delay = kwargs.get('measure_delay', 0),
                        dark = True,
                        preview = True,
                        verbose = False,
                    )
        self.control_keithley._reset_keithley()
        self.gantry.movetoload()
        