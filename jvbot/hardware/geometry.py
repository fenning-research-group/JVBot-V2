import numpy as np
from natsort import natsorted
import os
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
### https://stackoverflow.com/questions/15457786/ctrl-c-crashes-python-after-importing-scipy-stats
os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = (
    "1"  # to preserve ctrl-c with scipy loaded
)
from scipy.interpolate import LinearNDInterpolator, RBFInterpolator
from jvbot.hardware.old_gantry import Gantry
import yaml
from typing import Literal, Union, List, Tuple
from enum import StrEnum

MODULE_DIR = os.path.dirname(__file__)
CALIBRATION_DIR = os.path.join(MODULE_DIR, "calibrations")
with open(os.path.join(MODULE_DIR, "hardwareconstants.yaml"), "r") as f:
    constants = yaml.load(f, Loader=yaml.FullLoader)
with open(os.path.join(CALIBRATION_DIR, "tray_calibrations.yaml"), "r") as f:
    sample_sizes = [k for k in yaml.load(f, Loader=yaml.FullLoader).keys()]
# print(sample_sizes)
SizeOpts = StrEnum(
    "SampleSize",
    {k: k for k in sample_sizes}
)
class CoordinateMapper:
    def __init__(self, p0, p1):
        self.destination = np.asarray(p1)
        self.source = np.asarray(p0)
        self.rbf = RBFInterpolator(
            self.destination[:, :2], # Interpolate with RBF over p0 (X, Y) -> p1 (X, Y)
            self.source,
            kernel = "thin_plate_spline",
            smoothing = 1e-3*np.mean(np.linalg.norm(self.source, axis = 1)),
        )
        self.zinterp = LinearNDInterpolator(
            self.destination[:, :2], # Interpolate with LinearND p0 (X, Y) -> p1 Z
            self.source[:, 2]
        )
    def map(self, p):
        p = np.asarray(p)[:2]
        goal = self.rbf(p[None, :])[0]
        # goal[2] = self.zinterp(p[:2])
        return self.rbf(p[None, :])[0]


def map_coordinates(
        name: str,
        slots: list,
        gantry: Gantry,
        z_clearance: float = 5,
        sample_size: SizeOpts = SizeOpts.square_10mm
    ):
    """Prompts user to move probe head to target points on labware for calibration purposes.

    Parameters
    ----------
    name : str
        name of labware to save in filename of output calibrations yaml file
    slots : list
        str labels of target points of interest, e.g., ['I1', 'A1', 'A5', 'I5']
    gantry : Gantry
        Gantry object to move the motors around.
    z_clearance : float, optional
        Vertical offset (mm) from point initial guess to start at, 
        to prevent collision by initial misalignment, by default 5.
    sample_size : str, optional
        
    """
    points = np.asarray(points).astype(float).round(2) # destination coordinates
    p_prev = points[0]
    points_source_guess = points
    points_source_meas = []
    for slotname, p in zip(slots, points_source_guess):
        movedelta = p - p_prev
        gantry.moverel(*movedelta, zhop = True)
        print(f"Move to {slotname}")
        gantry.gui()
        points_source_meas.append(gantry.position)
        gantry.moverel(z = z_clearance, zhop = False)
        p_prev = p
    with open(os.path.join(CALIBRATION_DIR, f"{name}_calibration.yaml"), "r") as f:
        old = yaml.safe_load(f)
    out = {
        "p0": points_source_meas,
        "p1": np.asarray(points)
        .astype(float)
        .round(2)
        .tolist(),
    }
    old[sample_size].update(out)
    with open(os.path.join(CALIBRATION_DIR, f"{name}_calibration.yaml"), "w") as f:
        yaml.dump(old, f)
    return CoordinateMapper(p0=points_source_meas, p1 = points)

class Workspace:
    """
    General class for defining planar workspaces. Primary use is to calibrate the coordinate system of this workspace to the 
    reference workspace to account for any tilt/rotation/translation in workspace mounting.
    
    Paramters
    ---------
    name: str
        name of workspaces, for logging purposes.
    pitch : tuple
        Space between neighboring slots (x, y) (mm). Assumes workspace is 2D, orthogonal to `jvbot.jvbot.gantry.Gantry` Z axis.
    gridsize : tuple
        Number of slots available (x, y)
    gantry : `jvbot.hardware.gantry.Gantry`
        Gantry control object to move motors in calibration.
    p0 : list, optional
        Initial guess of lower left slot of labware, for calibration initial point
    testslots : list, optional
        Slots with which to calibrate the plane rotation matrix from. Defaults to None.
    z_clearance : float, optional
        Vertical clearance (mm) to give when calibrating points, to avoid crashes. Defaults to 5.
    sample_size: str, optiona;
        Which sample size is the workspace designed for, defaults to "square_10mm". 
        Must match the corresponding keys of the calibrations.yaml file.
    """

    def __init__(
        self,
        name: str,
        pitch: tuple,
        gridsize: tuple,
        gantry: Gantry = None,
        p0: Union[List[float], Tuple[float]] = [0, 0, 0],
        testslots: List[str] = None,
        z_clearance: float = 5,
        sample_size: SizeOpts = SizeOpts.square_10mm
    ):
        print("Initializing Workspace")
        self.__calibrated = False
        self.name = name
        self._SAMPLESIZEOPTION = sample_size
        if gantry is None:
            self.__is_simulation = True
            self.p0 = np.array([0, 0, 0])
        else:
            self.__is_simulation = False
            self.p0 = np.asarray(p0) + [0, 0, 5]
        self.gantry = gantry
        # frame of reference properties
        self.pitch = pitch
        self.gridsize = gridsize
        self.capacity = gridsize[0] * gridsize[1]
        self.z_clearance = z_clearance
        self.__generate_coordinates()
        if testslots is None:
            testslots = []
            for yidx, xidx in zip([0, -1, -1, 0], [0, 0, -1, -1]):
                testslots.append(
                    f"{self._ycoords[yidx]}{self._xcoords[xidx]}"
                )
            self.testslots = testslots
            self.testpoints = np.array(
                [self._coordinates[name] for name in testslots]
            ).astype(float32)
    def __generate_coordinates(self):
        def letter(num):
            return chr(ord("A") + num)
        self._coordinates = {}
        self._openslots = []
        self._xcoords = [
            letter(self.gridsize[0] - yidx - 1) for yidx in range(self.gridsize[0])
        ]
        self._ycoords = [
            xidx + 1 for xidx in range(self.gridsize[1])
        ]
        for xidx in range(self.gridsize[0]):
            for yidx in range(self.gridsize[1]):
                name = f"{self._xcoords[xidx]}{self._ycoords[yidx]}"
                self._coordinates[name] = [
                    xidx * self.pitch[0],
                    yidx * self.pitch[1],
                    0
                ]
    def slot_coordinates(self, name):
        if self.__calibrated == False:
            raise Exception(f"Need to calibrate {self.name} before use!")
        coords = self.transform.map(self._coordinates[name])
        if any(np.isnan(coords)):
            raise Exception(
                "Coordinate was transformed into nan! Check for rounding errors on calibration .yamls"
            )
        return self.transform.map(self._coordinates[name])
    def __call__(self, name):
        return self.slot_coordinates(name)
    def calibrate(self):
        if self.__is_simulation:
            raise Exception("Cannot calibrate a simulated workspace")
        self.gantry.moveto(*self.p0)
        self.transform = map_coordinates(
            self.name,
            self.testslots,
            self.testpoints,
            self.gantry,
            self.z_clearance,
            sample_size = self._SAMPLESIZEOPTION
        )
        self.__calibrated = True
    def _load_calibration(self):
        with open(
            os.path.join(CALIBRATION_DIR, f"{self.name}_calibration.yaml"), "r"
        ) as f:
            pts = yaml.load(f, Loader=yaml.FullLoader)[self._SAMPLESIZEOPTION]
        self.transform = CoordinateMapper(p0 = pts["p0"], p1 = pts["p1"])
        self.__calibrated = True
    def plot(tray, ax=None, is_samples = False, updated_colorscheme = False):
        """
        plot current contents of the labware
        """
        if ax is None:
            fig, ax = plt.subplots()
            ax.set_aspect("equal")

        plt.sca(ax)
        xvals = np.unique([x for x, _, _ in tray._coordinates.values()])
        yvals = np.unique([y for _, y, _ in tray._coordinates.values()])
        markersize = 30

        unique_substrates = {}
        empty_slots = {"x": [], "y": []}
        for k, (x, y, z) in tray._coordinates.items():
            if k in tray.contents:
                substrate = tray.contents[k].substrate
                if substrate not in unique_substrates:
                    unique_substrates[substrate] = {"x": [], "y": []}
                unique_substrates[substrate]["x"].append(x)
                unique_substrates[substrate]["y"].append(y)
            else:
                empty_slots["x"].append(x)
                empty_slots["y"].append(y)


        if updated_colorscheme:
            if is_samples: # sample trays
                cmap_x = plt.get_cmap('tab10', len(xvals))
                cmap_y = plt.get_cmap('plasma', len(yvals))
                cmap_2 = plt.get_cmap('PuBuGn', len(yvals))
                markers = ['o', 's', 'p', 'D', 'h', 'H']
            if not is_samples: # liquid labware trays
                cmap_x = plt.get_cmap('plasma', len(xvals)) 
                cmap_y = plt.get_cmap('tab10', len(yvals))
                markers = ['o', 's', 'D', 'p', 'h', 'H']
            norm_x = Normalize(vmin = min(xvals), vmax = max(xvals))
            norm_y = Normalize(vmin = min(yvals), vmax = max(yvals))

            markers_dict = {}
            if is_samples:
                for j, x in enumerate(xvals):
                    if j >= len(markers):
                        j = j - len(markers)
                    markers_dict[x] = markers[j]
                gamma = 0
                scatters = []
                labels = []
                for label, c in unique_substrates.items():
                    for c_x, c_y in zip(c["x"], c["y"]):
                        marker_0 = markers_dict[c_x]
                        if gamma%2:
                            facecolor_0 = cmap_2(norm_y(c_y))
                        else:
                            facecolor_0 = cmap_y(norm_y(c_y))
                        gamma += 1

                        sc = plt.scatter(c_x, c_y, label = label, marker = marker_0, facecolor = facecolor_0, edgecolor = 'black', s = 150)
                        scatters.append(sc)
                        labels.append(label)
                    # plt.scatter(c["x"], c["y"], label=label, marker=markers[c["x"]], facecolor = cmap_y(norm_y(c["y"])))
            if not is_samples:
                for j, y in enumerate(yvals):
                    if j >= len(markers):
                        j = j - len(markers)
                    markers_dict[y] = markers[j]
                for label, c in unique_substrates.items():

                    plt.scatter(c["x"], c["y"], label=label, marker=markers[c["y"]], facecolor = cmap_x(norm_x(c["x"])))
        if not updated_colorscheme:
            for label, c in unique_substrates.items():
                plt.scatter(c["x"], c["y"], label=label, marker="s")
        plt.scatter(empty_slots["x"], empty_slots["y"], c="gray", marker="x", alpha=0.2)
        if updated_colorscheme:
            plt.legend(scatters, labels, ncol = 5, bbox_to_anchor = (1.05, 1), loc = 2, borderaxespad = 0.0)
            # plt.legend(bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.0, ncol = 5)
        if not updated_colorscheme:
            plt.legend(bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.0)
        plt.title(tray.name)
        plt.yticks(
            yvals[::-1],
            [chr(65 + i) for i in range(len(yvals))],
        )
        plt.xticks(xvals, [i + 1 for i in range(len(xvals))])

    def plot_new(tray, ax=None, is_samples = False):
        if ax is None:
            fig, ax = plt.subplots()
            ax.set_aspect("equal")

        plt.sca(ax)
        xvals = np.unique([x for x, _, _ in tray._coordinates.values()])
        xvals = natsorted(xvals)
        # print(xvals)
        yvals = np.unique([y for _, y, _ in tray._coordinates.values()])
        yvals = natsorted(yvals)
        markersize = 30

        unique_substrates = {}
        empty_slots = {"x": [], "y": []}
        for k, (x, y, z) in tray._coordinates.items():
            if k in tray.contents:
                substrate = tray.contents[k].substrate
                if substrate not in unique_substrates:
                    unique_substrates[substrate] = {"x": [], "y": []}
                unique_substrates[substrate]["x"].append(x)
                unique_substrates[substrate]["y"].append(y)
            else:
                empty_slots["x"].append(x)
                empty_slots["y"].append(y)

        if is_samples: # sample trays
            cmap_x = plt.get_cmap('tab10', len(xvals))
            cmap_y = plt.get_cmap('plasma', len(yvals))
            cmap_2 = plt.get_cmap('PuBuGn', len(yvals))
            markers = ['o', 's', 'D', 'P', 'X', 'H']
        if not is_samples: # liquid labware trays
            cmap_x = plt.get_cmap('plasma', len(xvals)) 
            cmap_y = plt.get_cmap('tab10', len(yvals))
            markers = ['o', 's', 'D', 'P', 'X', 'H']
        norm_x = Normalize(vmin = min(xvals), vmax = max(xvals))
        norm_y = Normalize(vmin = min(yvals), vmax = max(yvals))
        # print(yvals)
        # print(xvals)
        colors_grid = {}
        for y in yvals:
            if np.where(yvals == y)[0][0]%2:
                color_opt = cmap_y(norm_y(y))
            else:
                color_opt = cmap_2(norm_y(y))
            colors_grid[y] = color_opt

        markers_dict = {}
        if is_samples:
            for j, x in enumerate(xvals):
                if j >= len(markers):
                    j = j - len(markers)
                markers_dict[x] = markers[j]
            gamma = 0
            x_coordinates = []
            y_coordinates = []
            colors = []
            markertypes = []
            scatters = []
            labels = []
            for label, c in unique_substrates.items():
                for c_x, c_y in zip(c["x"], c["y"]):
                    marker_0 = markers_dict[c_x]
                    # if gamma%2 == 0:
                    #     facecolor_0 = cmap_2(norm_y(c_y))
                    # else:
                    #     facecolor_0 = cmap_y(norm_y(c_y))

                    # gamma += 1
                    facecolor_0 = colors_grid[c_y]
                    sc = plt.scatter(c_x, c_y, label = label, marker = marker_0, facecolor = facecolor_0, edgecolor = 'black', s = 150)
                    x_coordinates.append(c_x)
                    y_coordinates.append(c_y)
                    colors.append(facecolor_0)
                    markertypes.append(marker_0)
                    scatters.append(sc)
                    labels.append(label)
                # plt.scatter(c["x"], c["y"], label=label, marker=markers[c["x"]], facecolor = cmap_y(norm_y(c["y"])))
        if not is_samples:
            for j, y in enumerate(yvals):
                if j >= len(markers):
                    j = j - len(markers)
                markers_dict[y] = markers[j]
            for label, c in unique_substrates.items():
                plt.scatter(c["x"], c["y"], label=label, marker=markers[c["y"]], facecolor = cmap_x(norm_x(c["x"])))
        
        ncols = len(xvals)
        nrows = len(yvals)
        grid = [[None for _ in range(ncols)] for _ in range(nrows)]
        color_grid = [[None for _ in range(ncols)] for _ in range(nrows)]
        marker_grid = [[None for _ in range(ncols)] for _ in range(nrows)]
        for xi, yi, label, c, m in zip(x_coordinates, y_coordinates, labels, colors, markertypes):
            # print(xi)
            # col_idx = np.where(xvals == xi)[0][0]
            # row_idx = np.where(yvals == yi)[0][0]
            col_idx = xvals.index(xi)
            row_idx = yvals.index(yi)
            grid[row_idx][col_idx] = label
            color_grid[row_idx][col_idx] = c
            marker_grid[row_idx][col_idx] = m
        
        plt.scatter(empty_slots["x"], empty_slots["y"], c="gray", marker="x", alpha=0.2)
        handles = []
        legend_labels = []
        for c in range(ncols):
            for r in reversed(range(nrows)):
                label = grid[r][c]
                color = color_grid[r][c]
                marker = marker_grid[r][c]
                if label is None:
                    handles.append(Line2D([0], [0], marker='x', linestyle = 'None'))
                    legend_labels.append("")
                else:
                    handles.append(Line2D([0], [0], marker = marker, linestyle = 'None', markersize = 8, color = color, markerfacecolor = color, markeredgecolor = 'black'))
                    legend_labels.append(label)

        ax.legend(handles, legend_labels, ncol = ncols,
                  bbox_to_anchor = (1.05, 1), frameon = True, handletextpad = 0.4, labelspacing = 0.6)

        # plt.scatter(empty_slots["x"], empty_slots["y"], c="gray", marker="x", alpha=0.2)
        # plt.legend(scatters, labels, ncol = 5, bbox_to_anchor = (1.05, 1), loc = 2, borderaxespad = 0.0)
            # plt.legend(bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.0, ncol = 5)
        plt.title(tray.name)
        plt.yticks(
            yvals[::-1],
            [chr(65 + i) for i in range(len(yvals))],
        )
        plt.xticks(xvals, [i + 1 for i in range(len(xvals))])


