from .base_motion import (
    BTTSKRMiniE3_MotionControl, Duet3Mini5PlusWiFi_MotionControl, 
    Duet3Mini5PlusEthernet_MotionControl, SerialCommunicator,
    SocketCommunicator, WiFiCommunicator, FakeCommunicator
)
import time
import re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, 
    QGridLayout, QPushButton
)
import PyQt5
import yaml
import os

from functools import partial
from .helpers import get_port

from typing import Union


MODULE_DIR = os.path.dirname(__file__)
with open(os.path.join(MODULE_DIR, "hardwareconstants.yaml"), "r") as f:
    constants = yaml.load(f, Loader=yaml.FullLoader)

class Gantry:
    """The Gantry control object for interfacing with 3-axis stepper motors.
    
    Primarily a wrapper around the MotionControl subclasses, for converting
    the expected Gantry methods into the backend MotionControl methods."""
    def __init__(
            self, 
            communicator: 
            Union[
                SerialCommunicator, SocketCommunicator, 
                FakeCommunicator, WiFiCommunicator
            ],
            controller:
            Union[
                BTTSKRMiniE3_MotionControl,
                Duet3Mini5PlusEthernet_MotionControl,
                Duet3Mini5PlusWiFi_MotionControl
            ]
        ):
        self.__comms = communicator()
        self._controls = controller(self.__comms)
        self._position = self._controls.position
        self._min_step = {
            "x_min": self._controls._config.grid_spacing_x,
            "y_min": self._controls._config.grid_spacing_y,
            "z_min": self._controls._config.grid_spacing_z,
        }
        print("Gantry ready to go!")
    
    @property
    def position(self):
        return self._controls.config.position
    @position.setter
    def position(self, pos):
        self._controls.config.position = pos

    @property
    def min_step(self):
        return self._min_step
    @min_step.setter
    def min_step(self, min_x: float = None, min_y: float = None, min_z: float = None):
        min_dict = {f"{ax}": ax for ax in [min_x, min_y, min_z] if ax is not None}
        self._min_step.update(min_dict)

    def connect(self):
        self._controls._comms.connect()
    
    def disconnect(self):
        self._controls._comms.disconnect()
    def set_defaults(self):
        self._controls.set_defaults
    def write(self, msg):
        self._controls._comms.write(msg)
    def _enable_steppers(self):
        self._controls._enable_steppers()
    def _disable_steppers(self):
        self._controls._disable_steppers()
    def update(self):
        self._controls.update()
    def gohome(self):
        self._controls.gohome()
    def set_speed_percentage(self, p):
        self._controls.set_speed_percentage(p = p)
    def movetoclear(self):
        self._controls.movetoclear()
    def movetoidle(self):
        self._controls.movetoidle()
    def moveto(self, x, y, z, zhop = True, speed = None):
        self._controls.moveto(x, y, z, zhop, speed)
    def premove(self, x, y, z, zhop = True):
        return self._controls.premove(x, y, z, zhop)
    def _transition_to_frame(self, target_frame):
        self._controls._transition_to_frame(target_frame = target_frame)
    def _target_frame(self, position: Union[tuple, list]):
        return self._controls._target_frame(position)
    def _waitformovement(self):
        return self._controls._waitformovement()
    def _movecommand(self, x: float, y: float, z: float, speed: float):
        return self._controls._movecommand(x = x, y = y, z = z, speed = speed)
    def _transform_coordinates(self, x, y, z):
        return self._controls._transform_coordinates(x, y, z)
    def moverel(
        self,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        zhop: bool = False,
        speed: float = None,
    ):
        self._controls.moverel(
            x = x,
            y = y,
            z = z,
            zhop = zhop,
            speed = speed
        )
    
    
    def gui(self):
        GantryGUI(gantry = self)

class GantryGUI:
    def __init__(self, gantry):
        AlignHCenter = PyQt5.QtCore.Qt.AlignHCenter
        self.gantry = gantry
        self.app = PyQt5.QtCore.QCoreApplication.instance()
        if self.app is None:
            self.app = QApplication([])
        self.app.aboutToQuit.connect(self.app.deleteLater)
        self.win = QWidget()
        self.grid = QGridLayout()
        self.stepsize = 1  # default step size, in mm

        ### axes labels
        for j, label in enumerate(["X", "Y", "Z"]):
            temp = QLabel(label)
            temp.setAlignment(AlignHCenter)
            self.grid.addWidget(temp, 0, j)

        ### position readback values
        self.xposition = QLabel("0")
        self.xposition.setAlignment(AlignHCenter)
        self.grid.addWidget(self.xposition, 1, 0)

        self.yposition = QLabel("0")
        self.yposition.setAlignment(AlignHCenter)
        self.grid.addWidget(self.yposition, 1, 1)

        self.zposition = QLabel("0")
        self.zposition.setAlignment(AlignHCenter)
        self.grid.addWidget(self.zposition, 1, 2)

        self.update_position()

        ### status label
        self.gantrystatus = QLabel("Idle")
        self.gantrystatus.setAlignment(AlignHCenter)
        self.grid.addWidget(self.gantrystatus, 5, 4)

        ### jog motor buttons
        self.jogback = QPushButton("Back")
        self.jogback.clicked.connect(partial(self.jog, y=-1))
        self.grid.addWidget(self.jogback, 3, 1)

        self.jogforward = QPushButton("Forward")
        self.jogforward.clicked.connect(partial(self.jog, y=1))
        self.grid.addWidget(self.jogforward, 2, 1)

        self.jogleft = QPushButton("Left")
        self.jogleft.clicked.connect(partial(self.jog, x=-1))
        self.grid.addWidget(self.jogleft, 3, 0)

        self.jogright = QPushButton("Right")
        self.jogright.clicked.connect(partial(self.jog, x=1))
        self.grid.addWidget(self.jogright, 3, 2)

        self.jogup = QPushButton("Up")
        self.grid.addWidget(self.jogup, 2, 3)
        self.jogup.clicked.connect(partial(self.jog, z=-1))

        self.jogdown = QPushButton("Down")
        self.jogdown.clicked.connect(partial(self.jog, z=1))
        self.grid.addWidget(self.jogdown, 3, 3)

        ### step size selector buttons
        self.steppt1 = QPushButton("0.1 mm")
        self.steppt1.clicked.connect(partial(self.set_stepsize, stepsize=0.1))
        self.grid.addWidget(self.steppt1, 5, 0)
        self.step1 = QPushButton("1 mm")
        self.step1.clicked.connect(partial(self.set_stepsize, stepsize=1))
        self.grid.addWidget(self.step1, 5, 1)
        self.step10 = QPushButton("10 mm")
        self.step10.clicked.connect(partial(self.set_stepsize, stepsize=10))
        self.grid.addWidget(self.step10, 5, 2)

        self.stepsize_options = {
            0.1: self.steppt1,
            1: self.step1,
            10: self.step10,
        }

        self.set_stepsize(self.stepsize)

        self.run()

    def set_stepsize(self, stepsize):
        self.stepsize = stepsize
        for setting, button in self.stepsize_options.items():
            if setting == stepsize:
                button.setStyleSheet("background-color: #a7d4d2")
            else:
                button.setStyleSheet("background-color: None")

    def jog(self, x=0, y=0, z=0):
        self.gantrystatus.setText("Moving")
        self.gantrystatus.setStyleSheet("color: red")
        self.gantry.moverel(x * self.stepsize, y * self.stepsize, z * self.stepsize)
        self.update_position()
        self.gantrystatus.setText("Idle")
        self.gantrystatus.setStyleSheet("color: None")

    def update_position(self):
        for position, var in zip(
            self.gantry.position, [self.xposition, self.yposition, self.zposition]
        ):
            var.setText(f"{position:.2f}")

    def run(self):
        self.win.setLayout(self.grid)
        self.win.setWindowTitle("JVBot Gantry GUI")
        self.win.setGeometry(300, 300, 500, 150)
        self.win.show()
        self.app.setQuitOnLastWindowClosed(True)
        self.app.exec_()
        return