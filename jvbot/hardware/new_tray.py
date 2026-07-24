import os
import yaml
from typing import List, Literal
from jvbot.hardware.gantry import Gantry
from jvbot.hardware.geometry import Workspace
MODULE_DIR = os.path.dirname(__file__)
TRAY_VERSIONS_DIR = os.path.join(MODULE_DIR, "tray_versions")
AVAILABLE_VERSIONS = {
    os.path.splitext(f)[0]: os.path.join(TRAY_VERSIONS_DIR, f)
    for f in os.listdir(TRAY_VERSIONS_DIR)
    if '.yaml' in f
}

def available_versions(self):
    return AVAILABLE_VERSIONS

def get_sizekey(size_str):
    if '.' in size_str:
        bef, aft = size_str.split('.')
        size_str = f"{bef}-{aft}"
    return size_str

class SampleTray(Workspace):
    def __init__(
        self,
        name,
        version,
        gantry: Gantry,
        testslots: List[str],
        p0 = [0, 0, 0],
        sample_size: str = "square_10mm"
    ):
        print(sample_size)
        print(get_sizekey(sample_size))
        constants, workspace_kwargs = self._load_version(version, sample_size = get_sizekey(size_str = sample_size))
        super().__init__(
            name = name, gantry = gantry, testslots = testslots, p0=p0, **workspace_kwargs
        )
        self.contents = {}
    def _load_version(self, version, sample_size):
        if version not in AVAILABLE_VERSIONS:
            raise Exception(
                f'Invalid tray version "{version}".\n\tAvailable version are: {list(AVAILABLE_VERSIONS.keys())}.'
            )
        with open(AVAILABLE_VERSIONS[version], "r") as f:
            constants = yaml.load(f, Loader=yaml.FullLoader)[sample_size]
        workspace_kwargs = {
            "pitch": (constants["xpitch"], constants["ypitch"]),
            "gridsize": (constants["numx"], constants["numy"]),
            "z_clearance": constants["z_clearance"],
        }
        return constants, workspace_kwargs
    def export(self, fpath):
        """
        routine to export tray data to save file. used to keep track of experimental conditions in certain tray.
        """
        return None

class Tray10mm(SampleTray):
    "Wrapper class with default arguments for the 10mmx10mm single pixel device layout."
    def __init__(self, version="tray_v1", gantry=None, p0=[0, 0, 0], sample_size: str = "square_10mm"):
        super().__init__(
            name="Tray10mm", version=version, gantry=gantry, p0=p0, testslots = ["I1"], sample_size = sample_size
        )