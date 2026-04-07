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

from .hardware.gantry import Gantry
from .hardware.control5 import Control_Keithley
from .hardware.tray import Tray

class JVControl:
    def __init__(self, area = 0.048, Eric_Opt = None):
        self.area = area # cm2
        if Eric_Opt is None:
            response = self._prompt_for_input("Do you want to use Eric's Scan-Rate Sweeps or Dark JV's? (y/n)")
            if response in ['y', 'Y']:
                self.control_keithley = Control_Keithley(area = self.area, ScanRateDarkJV = True)
            else:
                self.control_keithley = Control_Keithley(area = self.area, ScanRateDarkJV = False)
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
        