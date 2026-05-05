"""This file contains the core logic of handling a modality of motion control in JVBot.

Classes
-------
ConnectConfig: Type[BaseConstantsConfig]
    Dataclass container to hold hardwareconstants relevant to some form of hardware communication.
MotionConfig: Type[BaseConstantsConfig]
    Dataclass container to hold hardwareconstants relevant to some form of gantry motion control.
GridConfig: Type[MotionConfig]
    Wrapper of MotionConfig to also include hardwareconstants relevant to gantry-space 3D discrete mappings.
Frames: Type[Enum]
    Enumeration class to match pre-allocation gantry coordinate sets in partitions.

BaseCommunicator: Type[abc.ABC]
    Base class to define fundamental hardware communication logic
SerialCommunicator: Type[BaseCommunicator]
    Wrapper of BaseCommunicator specialized to interface with BigTreeTech SKR Mini E3 V2.0 motion control 
    over a wired USB connection.
SocketCommunicator: Type[BaseCommunicator]
    Wrapper of BaseCommunicator specialized to interface with a Duet 3 Mini 5+ Ethernet motion control 
    board over a wired Ethernet TCP connection.
WiFiCommunicator: Type[SocketCommunicator]
    Wrapper of SocketCommunicator specialized to interface with a Duet 3 Mini 5+ WiFi motion control
    board over the wireless connection.
FakeCommunicator: Type[SocketCommunicator]
    Wrapper of SocketCommunicator designed to simulate Duet 3 Mini 5+ motion control board communications
    for testing of non-communication errors of the gantry module.

BaseMotionControl: Type[abc.ABC]
    Base class to define fundamental cartesian X,Y,Z motion logic over g-code commands to motor drivers.
DiscreteMotionControl: Type[BaseMotionControl]
    Wrapper of BaseMotionControl to handle conversion of continuous 3-space into discrete 3-space to 
    minimize accumulation of positional errors of open-loop stepper motors in long-term operation.
BTTSKRMiniE3_MotionControl: Type[BaseMotionControl]
    Wrapper of BaseMotionControl to implement the SerialCommunicator with the g-code logic
Duet3Mini5PlusEthernet_MotionControl: Type[DiscreteMotionControl]:
    Wrapper of DiscreteMotionControl to implement the SocketCommunicator with the G-code logic

Errors
------
HomingError:
    Exception raised if the gantry has not been homed before a motion is attempted.
FrameError:
    Exception raised if the gantry needs to transition between coordinate frames of reference.
    e.g., if some region of the gantry's maximum range of motion has geometric constraints.
TargetError:
    Exception raised if the positional target of the move command is outside of the 
    allowed domain of gantry motion.

"""


from dataclasses import dataclass, fields, _MISSING_TYPE, field
from abc import ABC, abstractmethod
from enum import Enum
import time
import re
from typing import Union, Set, List, Optional, Tuple, Generic, TypeVar
import serial
import socket
import websockets
import numpy as np
try:
    from typing import Literal
except:
    from typing_extensions import Literal
import os
import yaml

from .base_config import BaseConstantsConfig

MODULE_DIR = os.path.dirname(__file__)
with open(os.path.join(MODULE_DIR, "hardwareconstants.yaml"), "r") as f:
    constants = yaml.load(f, Loader = yaml.FullLoader)

AllowedFrames = Literal["invalid", "workspace", "opentrons"]

# AllowedFrames = Literal["invalid", "workspace", "opentrons"]
# Motion / Communication Exceptions:
class HomingError(Exception):
    """Exception raised if a moving tool has not yet been homed."""
    def __init__(
            self, 
            message = "Uh-oh, Looks like the Gantry has not been homed! Be sure to run the .gohome() method first."
    ):
        self.message = message
        super().__init__(self.message) # pass the exception message through to the base Exception

class FrameError(Exception):
    """Exception raised if the target coordinate is not in a pre-defined frame of reference."""
    def __init__(
        self,
        position: tuple,
    ):
        self.message = f"Coordinate [{position[0]}, {position[1]}, {position[2]}] is not within the defined frames!"
        super().__init__(self.message)

class TargetError(Exception):
    """Exception raised if the target coordinate is not given to the `premove()` method of a class inheritor of BaseMotionControl"""
    def __init__(self):
        super().__init__("Cannot move to a coordinate that is [None, None, None]!")


@dataclass
class ConnectConfig(BaseConstantsConfig):
    """dataclass for storing base properties used to set up communications."""
    POLLINGDELAY: float = 0.05
    port: Union[str, None] = ""
    ip: Union[str, None] = ""

@dataclass
class MotionConfig(BaseConstantsConfig):
    """dataclass for storing the base properties used for continuous motion control"""
    # Motion Planning:
    position: Union[tuple, list] = field(default_factory = list)
    TRANSITION_COORDINATES: Union[tuple, list] = field(default_factory = list)
    CLEAR_COORDINATES: Union[tuple, list] = field(default_factory = list)
    IDLE_COORDINATES: Union[tuple, list] = field(default_factory = list)
    _targetposition: tuple = field(default_factory = tuple)
    _currentframe: str = ""
    _ZLIM: float = 1
    TRANSITION_NUDGE: float = 1
    # Motion Execution:
    MAXSPEED: float = 1
    MINSPEED: float = 1
    ZHOP_HEIGHT: float = 1
    in_use: bool = True
    GANTRYTIMEOUT: float = 1

@dataclass
class GridConfig(MotionConfig):
    """dataclass for storing the base properties used for discrete motion control."""
    grid_spacing_x: float = 1
    grid_spacing_y: float = 1
    grid_spacing_z: float = 1

ConfigVar = TypeVar("ConfigVar", bound = MotionConfig)

class Frames(str, Enum):
    """Enumeration of subspaces of the workspace"""
    Workspace = "workspace"
    Opentrons = "opentrons"
    Invalid = "invalid"

# Communication Methods

class BaseCommunicator(ABC):
    def __init__(self, config: ConnectConfig = ConnectConfig()):
        self._config = config
    
    @property
    def config(self) -> ConnectConfig:
        return self._config

    # abstractmethods
    @abstractmethod
    def connect(self, port: Union[str, None], ip: Union[str, None]) -> Union[serial.Serial, socket.socket, websockets.WebSocketClientProtocol]:
        """Setup the communication link."""
        raise NotImplementedError
    @abstractmethod
    def write(self, msg) -> list:
        """Send a GCode command through the communicator, 
        split the response by line breaks, return as list"""
        raise NotImplementedError
    
    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect, delete the communication link."""
        raise NotImplementedError
    
    @abstractmethod
    def _send_echo(self, stop_moving: bool = True):
        """Sends an echo command to the communicator."""
        raise NotImplementedError
    
    @abstractmethod
    def _search_for_echo(self):
        """Search for the most recent echo response from the communicator."""
        raise NotImplementedError
    
    @abstractmethod
    def _ready_to_talk(self) -> bool:
        """Checks if self._handle has bytes available for reading."""
        raise NotImplementedError

class SerialCommunicator(BaseCommunicator):
    """Communication via serial connection to execute commands.

    Parameters
    ----------
    BaseCommunicator : _type_
        _description_
    """

    def __init__(self, port: str = None):
        self._constants = constants["gantry_v2"]["serial_connection"]
        setup_connect_constants(
            communicator_instance = self
        )
        if port is None:
            self.config.port = get_port(
                device_identifiers = self.config.device_identifiers
            )
        else:
            self.config.port = port
        self._connect()

    def connect(self) -> serial.Serial:
        self._comms = serial.Serial(port = self.config.port, timeout = 1, baudrate = 115200)
    
    def disconnect(self):
        self._comms.close()
        del self._comms
    
    def _ready_to_talk(self):
        return self._comms.in_waiting
    
    def _send_echo(self, stop_moving = True):
        if not stop_moving:
            raise NotImplementedError("frgpascal.hardware.gantry.SerialCommunicator is only configured to send echos regarding motion control.")
        echo_command = "M118 E1 FinishedMoving"
        self._comms.write(echo_command)
    
    def _search_for_echo(self, stop_moving = True):
        return self._comms.readline().decode("utf-8").strip()
    
    def write(self, msg: str) -> List[str]:
        self._comms.write(
            f"{msg}\n".encode()
        )
        time.sleep(self.config.POLLINGDELAY)
        output = []
        while self._comms.in_waiting:
            line = self._comms.readline().decode("utf-8").strip()
            if line != "ok":
                output.append(line)
            time.sleep(self.config.POLLINGDELAY)
        return output

class SocketCommunicator(BaseCommunicator):
    """Communication via socket connection to execute commands.
    """

    def __init__(self):
        self._constants = constants["gantry_v2"]["socket_connection"]
        super().__init__()
        setup_connect_constants(
            communicator_instance = self
        )
        # self.connect()

    def connect(self) -> socket.socket:
        """Connect to a socket communication."""
        if self.config.ip in self.config._connected_network_devices:
            print(f"The device at {self.config.ip} is already connected!")
            return self.config._connected_network_devices[self.config.ip]
        # Can we talk with the device? (deprecated)
        # if not self.ping_device(ip = self.ip):
            # raise ValueError(f"Device at {self.config.ip}:{self.config.port} is not reachable (ping failed)!")
        try:
            for port in ["23", "21", "80"]:
                try:
                    print(f"Trying to connect to device at {self.config.ip}:{port}...")
                    self._handle = socket.create_connection((self.config.ip, port), timeout = 5)
                    if port == "21":
                        print(f"\tDevice conneted over OTHER type connection")
                    elif port == "23":
                        print(f"\tDevice connected over TCP type connection")
                    elif port == "80":
                        print(f"\tDevice connected over HTTP type connection")
                    self.config.port = port
                    break
                except Exception as e:
                    print(f"\t Connecting at {self.config.ip}:{port} failed \n\t{e}")
                    self.disconnect()
            self.config._connected_network_devices[self.config.ip] = self._handle
        except Exception as e:
            raise ValueError(f"Failed to connect to Duet at {self.config.ip} for any ports [23, 21, 80]!\n{e}")
    
    def disconnect(self):
        """Disconnect the socket communication."""
        self._handle.close()
        try:
            self.config._connected_network_devices.pop(self.config.ip)
        except KeyError:
            self.config._connected_network_devices = {}
        del self._handle
    
    def send_gcode(self, command, homing = True):
        """
        Send a G-code command to a device over the SocketCommunicator._handle socket object.

        Parameters
        ----------
        command : str
            The G-Code to send
        homing : bool, optional
            If True, removes timeout to collect response from socket (Default setting)
            If False, sets timeout for response from socket to 30 seconds
        """
        if not self._handle:
            raise ValueError("socket is not connected, be sure to run .connect() first!")
        self._handle.sendall((command + "\n").encode("utf-8"))
        bytes_to_receive = 1024
        if homing:
            self._handle.settimeout(None)
            response_0 = self._handle.recv(bytes_to_receive).decode("utf-8")
            response = response_0.split()
            self._handle.settimeout(30)
        else:
            response = [self._handle.recv(bytes_to_receive).decode("utf-8").strip()]
        return response
    
    def write(self, msg: str) -> List[str]:
        response = self.send_gcode(command = msg)
        return response
    
    def _ready_to_talk(self) -> bool:
        return True
    
    def _send_echo(self, stop_moving = True):
        if not stop_moving:
            raise NotImplementedError("frgpascal.hardware.gantry.SerialCommunicator is only configured to send echos regarding motion control.")
        echo_command = 'M118 S"FinishedMoving"'
        self._handle.sendall((echo_command + "\n").encode("utf-8"))
    
    def _search_for_echo(self):
        return self._handle.recv(1024).decode("utf-8").strip()

class FakeCommunicator(SocketCommunicator):
    def connect(self):
        self._handle = None
    def disconnect(self):
        print("Disconnected")
        # del self._handle
    def send_gcode(self, command, homing = True):
        return ["M114 X0.00 Y0.00 Z0.00"]
    def _send_echo(self, stop_moving = True):
        return "echo sent"
    def _search_for_echo(self):
        return "FinishedMoving"

class WiFiCommunicator(BaseCommunicator):
    def __init__(self):
        raise NotImplementedError("Support for websockets connection is planned for future development.")


# Communication Methods

class BaseMotionControl(ABC, Generic[ConfigVar]):
    def __init__(self, config: ConfigVar, communicator: BaseCommunicator):
        self._config = config
        self._speed = self._config.MAXSPEED
        self._position = self._config.position
        self._comms = communicator
    # abstract properties
    @property
    def speed(self) -> float:
        return self._speed
    
    @speed.setter
    def speed(self, value):
        self._speed = value
        self._comms.write(
            msg = f"G0 F{value}"
        )

    @property
    def position(self) -> List:
        return self._position
    
    @position.setter
    def position(self, pos):
        self._position = pos

    # concrete properties
    @property
    def config(self) -> MotionConfig:
        return self._config

    # abstract methods
    @abstractmethod
    def set_defaults(self):
        """Sends set of GCode commands to ensure default configuration is properly set."""
        raise NotImplementedError
    
    # communal methods, same across all inheritors

    def gohome(self):
        self._comms.write("G28 Z")
        self.update()
        self._comms.write("G28 X Y")
        self.movetoload()
    def _enable_steppers(self):
        """Send M17 GCode command to turn on the stepper motors"""
        self._comms.write("M17")
    
    def _disable_steppers(self):
        """Send M18 GCode command to turn on the stepper motors"""
        self._comms.write("M18")
    
    def set_speed_percentage(self, p):
        """Set the max allowed motion speed to a percentage 0-100% of max possible motion speed"""
        if (p < 0) or (p > 100):
            raise Exception("Speed must be set by a percentage value between 0-100!")
        self.speed = (p / 100) * (self.MAXSPEED - self.MINSPEED) + self.MINSPEED
    
    def _target_frame(self, position: Union[tuple, list]) -> Set[Frames]: # validate that the AllowedFrames are the only options defined for this codebase.
        """
        Determine which frame contains the position.

        Parameters
        ----------
        position : Union[tuple, list]
            [x, y, z] coordinate of point in rectangular space.

        Returns
        -------
        Set[Frames]
            name of frame. if none, returns "invalid".
        """
        for frame, lims in self.config._FRAMES.items():
            print(f"\tchecking frame {frame}")
            for idx, coord in enumerate(["x", "y", "z"]):
                v = position[idx]
                if v is not None:
                    if (v < lims[f"{coord}_min"]) or (v > lims[f"{coord}_max"]):
                        print(f"\t\t{v} is outside bounds of {coord}-axis!")
                        continue
            print(f"\t\tThe position {position} is inside of frame {frame}")
            return frame
        return "invalid"
    
    def _transition_to_frame(self, target_frame: Set[Frames]) -> None:
        """
        Gently move the gantry between frames near the transition coordinate

        Parameters
        ----------
        target_frame : Set[Frames]
            The frame to transition into.
        """
        x, y, z = self.config.TRANSITION_COORDINATES
        if target_frame == "opentrons":
            x -= self.config.TRANSITION_NUDGE
        else:
            x += self.config.TRANSITION_NUDGE
        self.config._ZLIM = self.config._FRAMES[f"{target_frame}"]["z_max"]
        self._movecommand(
            x, y, z, speed = self.speed
        )


    def update(self):
        found_coordinates = False
        while not found_coordinates:
            output = self._comms.write("M114") # get current position
            for line in output:
                if line.startswith("X:"):
                    x = float(re.findall(r"X:(\S*)", line)[0])
                    y = float(re.findall(r"Y:(\S*)", line)[0])
                    z = float(re.findall(r"Z:(\S*)", line)[0])
                    found_coordinates = True
                    break

            self.config.position = [x, y, z]
            self.config._currentframe = self._target_frame(self.config.position)
            print(f"\t\t{self._currentframe}")
            self.config._ZLIM = self.config._FRAMES[self.config._currentframe]["z_max"]

    def _transform_coordinates(
            self,
            x: float,
            y: float,
            z: float,
    ):
        """transform provided coordinates into alternative basis.

        Identity transform at base, for upgrading within inheriting class.

        Parameters
        ----------
        x : float
            x_coordinate, in mm
        y : float
            y_coordinate, in mm
        z : float
            z_coordinate, in mm

        Returns
        -------
        tuple
            target coordinates for this motion.
        """
        return x, y, z

    def premove(
            self, 
            x: float, 
            y: float, 
            z: float, 
    ) -> tuple:
        """
        Check to confirm that all target positions are valid.

        Parameters
        ----------
        x : float
            target coordinate along x-axis to validate
        y : float
            target coordinate along x-axis to validate
        z : float
            target coordinate along x-axis to validate
        
        Returns
        -------
        tuple
            (x, y, z) position, if valid.
        
        Raises
        ------
        HomingError
            If the gantry has not been homed, then we cannot move to controlled positions.
        """
        if self.config.position == [None, None, None]:
            raise HomingError()
        # do we transition between opentrons/workspace? if so, handle it.
        target_frame = self._target_frame(position = (x, y, z))
        # cur_frames = list(self.config._FRAMES.keys())
        # if target_frame not in cur_frames:
            # print(f"frame {target_frame} is not in the defined frames!")
        if target_frame == "invalid":
            raise FrameError()
        if self.config._currentframe != target_frame:
            print(f"\ttime to transition to a new frame")
            self._transition_to_frame(target_frame)
        return x, y, z
    
    def moveto(
            self,
            x: Optional[Union[float, List[float]]] = None,
            y: Optional[float] = None,
            z: Optional[float] = None,
            zhop: Optional[bool] = True,
            speed: Optional[float] = None,
    ):
        """Move the gantry to provided x, y, z coordinates.

        Parameters
        ----------
        x : Optional[Union[float, List[float]]], optional
            If is a float, then is the x-coordinate to move to.
            If is a list, then is the [x, y, z] coordinate to move to.
            Defaults to None.
        y : Optional[float], optional
            y-coordinate to move to, defaults to None.
        z : Optional[float], optional
            z-coordinate to move to, defaults to None
        zhop : Optional[bool], optional
            Whether to jog upwards in z-axis at begin/end of move,
            to avoid crashing the gripper head. Defaults to True.
        speed : Optional[float], optional
            Speed to overwrite default for this move only, defaults to None.
        
        Raises
        ------
        TargetError
            If all of {x, y, z} are None, then there is no defined coordiante to move to.
        """
        try:
            if len(x) == 3:
                y = x[1]
                z = x[2]
                x = x[0]
            # x_, y_, z_ = tuple(x)
            # x, y, z = tuple(x_, y_, z_)
        except:
            pass
        if (x is None) and (y is None) and (z is None):
            raise TargetError()
        print(x, y, z)
        # if len(x) == 3:
        x, y, z = self._transform_coordinates(x, y, z)
        x, y, z = self.premove(x, y, z)
        if (x == self.config.position[0]) and (y == self.position[1]):
            zhop = False #why zhop if no lateral movement
        if zhop:
            z_ceiling = max(self.config.position[2], z) + self.config.ZHOP_HEIGHT
            z_ceiling = min(z_ceiling, self.config._ZLIM)
            self.moveto(x, y, z_ceiling, zhop = False, speed = speed)
            self.moveto(x, y, z_ceiling, zhop = False)
            self.moveto(z = z, zhop = False, speed = speed)
        else:
            self._movecommand(x, y, z, speed)
    
    def movetoload(self):
        self.moveto(self.config.LOAD_COORDINATES)
    def moverel(
            self,
            x: Optional[float] = 0,
            y: Optional[float] = 0,
            z: Optional[float] = 0,
            zhop: Optional[bool] = False,
            speed: Optional[float] = None,
    ):
        """Move relative to the current position.

        Parameters
        ----------
        x : Optional[float], optional
            mm to move along x-axis, defaults to 0 mm.
        y : Optional[float], optional
            mm to move along y-axis, defaults to 0 mm.
        z : Optional[float], optional
            mm to move along z-axis, defaults to 0 mm.
        zhop : Optional[bool], optional
            Whether to jog upwards in z-axis at begin/end of move,
            to avoid crashing the gripper head. Defaults to False.
        speed : Optional[float], optional
            Speed to overwrite default for this move only, defaults to None.
        """
        x += self.config.position[0]
        y += self.config.position[1]
        z += self.config.position[2]
        self.moveto(x, y, z, zhop, speed)
    
    def _movecommand(
        self,
        x: float,
        y: float,
        z: float,
        speed: Optional[float] = None,
    ) -> bool:
        """Send a controlled linear motion command to the communicator

        Parameters
        ----------
        x : Optional[float], optional
            mm to move along x-axis, defaults to 0 mm.
        y : Optional[float], optional
            mm to move along y-axis, defaults to 0 mm.
        z : Optional[float], optional
            mm to move along z-axis, defaults to 0 mm.
        speed : Optional[float], optional
            Speed to overwrite default for this move only, defaults to None.
        
        Returns
        -------
        bool
            _description_
        """
        if [p == c for p, c in zip(self.config.position, [x, y, z])]:
            return True
        reset_speed = self.speed
        if speed is None:
            speed = self.speed
            reset_speed = None
        self.config._targetposition = [x, y, z]
        self._comms.write(f"G1 X{x} Y{y} Z{z} F{speed}")
        done_moving = self._waitformovement()
        if reset_speed is not None:
            self._comms.write(f"G0 F{reset_speed}")
        return done_moving

    def _waitformovement(self) -> bool:
        """Confirm that the gantry has reached target position.

        Returns
        -------
        bool
            Returns False if target position is not reached
            in the time allotted by self.config.GANTRYTIMEOUT
        """
        self.config.in_motion = True
        start_time = time.time()
        time_elapsed = time.time() - start_time
        self._comms.write("M400")
        self._send_echo(stop_moving = True)

        reached_destination = False
        while (not reached_destination) and (time_elapsed < self.config.GANTRYTIMEOUT):
            print("Are we there yet?")
            time.sleep(self._comms.config.POLLINGDELAY)
            yapping = self._comms._ready_to_talk()
            while yapping:
                print("Ready to talk")
                done_move = self._comms._search_for_echo()
                if done_move:
                    self.update()
                    if (
                        np.linalg.norm(
                            [
                                a - b 
                                for a, b in zip(
                                    self.config.position,
                                    self.config._targetposition
                                )
                            ]
                        )
                    ):
                        reached_destination = True
                        yapping = False
                time.sleep(self._comms.config.POLLINGDELAY)
        self.config.in_motion = ~reached_destination
        self.update()
        return reached_destination

class DiscreteMotionControl(BaseMotionControl[GridConfig]):

    def _transform_coordinates(self, x: float, y: float, z: float) -> Tuple[int, int, int]:
        """Map provided target position into discrete grid coordinates:

        Parameters
        ----------
        x : float
            target x_coordinate, in mm.
        y : float
            target y_coordinate, in mm.
        z : float
            target z_coordinate, in mm.

        Returns
        -------
        Union[Tuple[int, int, int], List[int, int, int]]
            The nearest grid coordinates for the target coordinates.
        """
        if x is not None:
            x = int(round(x / self.config.grid_spacing_x)) * self.config.grid_spacing_x
        if y is not None:
            y = int(round(y / self.config.grid_spacing_y)) * self.config.grid_spacing_y
        if z is not None:
            z = int(round(z / self.config.grid_spacing_z)) * self.config.grid_spacing_z
        return (x, y, z)
    
class BTTSKRMiniE3_MotionControl(BaseMotionControl):

    def __init__(self, communicator: SerialCommunicator):
        self._constants = constants["gantry_v2"]["serial_connection"]
        self._config = MotionConfig()
        setup_motion_constants(
            controller_instance = self
        )
        super().__init__(config = self._config, communicator = communicator)

    def set_defaults(self):
        self.write("M501")   # load defaults from EEPROM
        self.write("G90")   # absolute coordinate system
        self.write("M92 X53") # set steps/mm if using 3mm pitch belts om x-axis
        self.write(
            "M906 X800 Y800 Z800 E1"
        )   # set max steppmer RMS currents (mA) per axis. E = extruder, unused to set low
        self.write(
            f"M203 x{self.config.MAXSPEED} Y{self.config.MAXSPEED} Z20.00"
        )   # set max speeds, mm/s. Z is hardcoded, limited by lead screw hardware
        self.write(
            "M84 S0"
        )   # disable stepper timeout, steppers remain engaged all the time
        self.set_speed_percentage(80)

class Duet3Mini5PlusEthernet_MotionControl(DiscreteMotionControl):

    def __init__(self, communicator: Union[SocketCommunicator, WiFiCommunicator]):
        if isinstance(communicator, SocketCommunicator):
            comms_type = "ethernet"
        elif isinstance(communicator, WiFiCommunicator):
            comms_type = "wifi"
        self._constants = constants["gantry"][f"{comms_type}_connection"]
        self._config = GridConfig()
        setup_motion_constants(
            controller_instance = self
        )
        super().__init__(config = self._config, communicator = communicator)

    def set_defaults(self):
        self.write("M501")
        self.write("G90")

    def update(self):
        found = {f"{ax}": False for ax in ["X", "Y", "Z"]}
        found_coordinates = False
        while not found_coordinates:
            output = self._comms.write("M114") # get current position
            for line in output:
                if line.startswith("X:"):
                    x = float(re.findall(r"X:(\S*)", line)[0])
                    found["X"] = True
                if line.startswith("Y:"):
                    y = float(re.findall(r"Y:(\S*)", line)[0])
                    found["Y"] = True
                if line.startswith("Z:"):
                    z = float(re.findall(r"Z:(\S*)", line)[0])
                    found["Z"] = True
                if sum([found[ax] for ax in ["X", "Y", "Z"]]) == 3:
                    found_coordinates = True
                    break

            self.config.position = [x, y, z]
            self.config._currentframe = self._target_frame(self.config.position)
            print(f"\t\t{self.config._currentframe}")
            self.config._ZLIM = self.config._FRAMES[self.config._currentframe]["z_max"]


# Load from hardware constants into the configurations:
def setup_constants(obj_instance, attr_info):
    """Scrapes the hardware constants.
    
    Adds attrs from attr_info into the configuration of the provided obj_instance
    
    Parameters
    ----------
    obj_instance : Union[BaseMotionControl, DiscreteMotionControl, BaseCommunicator, SerialCommunicator, SocketCommunicator, WebsocketCommunicator]

    attr_info : List[Tuple]
        Each element of attr_info should be of the form (str(attribute name), Union[str(key for relevant value in yaml), (default value if not in yaml)])
    """
    for ati in attr_info:
        # print(ati)
        # print(obj_instance._config)
        name_, val_ = ati
        print(name_, val_)
        # print(obj_instance._constants)
        if isinstance(val_, dict):
            if "device_identifiers" == name_:
                val = {k: obj_instance._constants[k][v] for k, v in val_.items()}
            elif "grid_spacing" in name_ or "ip" in name_:
                print(val_)
                vd = {k: obj_instance._constants[k][v] for k, v in val_.items()}
                print(vd)
                vv = [v for k, v in vd.items()][0]
                print(type(vv), vv)
                val = vv
            elif ("_" in name_) and (not val_):
                print(f"\t{name_}\t{val_}")
                val = {k: obj_instance._constants[v] for k, v in val_.items()}
            elif ("_" in name_) and (val_) and ("FRAMES" not in name_):
                print(name_, val_)
                val = {}
            elif ("FRAMES" in name_):
                print(val_)
                val = {k: obj_instance._constants[v] for k, v in val_.items()}
            else:
                val = {k: obj_instance._constants[k][v] for k, v in val_.items()}
        elif isinstance(val_, str):
            val = obj_instance._constants[val_]
        else:
            val = val_
        # print(name_, val)
        setattr(
            obj_instance._config,
            name_,
            val
        )

def setup_motion_constants(controller_instance: Union[BaseMotionControl, BTTSKRMiniE3_MotionControl, DiscreteMotionControl, Duet3Mini5Plus_MotionControl]):
    """
    Scrape the hardware constants for the given controller_instance.

    Adds common attributes for motion control into the controller config.
    Parameters
    ----------
    controller_instance : 
        _description_
    """
    attr_info = [
        # (name, constants key)
        # ("_OVERALL_LIMS", "overall_gantry_limits"),
        # ("_FRAMES", {"workspace": "workspace_limits", "opentrons": "opentrons_limits"}),
        # ("TRANSITION_COORDINATES", "transition_coordinates"),
        # ("CLEAR_COORDINATES", "clear_coordinates"),
        ("LOAD_COORDINATES", "load_coordinates"),
        # ("TRANSITION_NUDGE", "transition_nudge"),
        # ("_currentframe", None),
        ("_ZLIM", None),
        ("position", [None, None, None]),
        ("_targetposition", [None, None, None]),
        ("GANTRYTIMEOUT", "timeout"),
        ("POSITIONTOLERANCE", "positiontolerance"),
        ("MAXSPEED", "speed_max"),
        ("MINSPEED", "speed_min"),
        ("ZHOP_HEIGHT", "zhop_height"),
        # ("in_use", True)
    ]
    if isinstance(controller_instance, DiscreteMotionControl) or isinstance(controller_instance, Duet3Mini5Plus_MotionControl):
        for axis in ["x", "y", "z"]:
            attr_info.append(
                (f"grid_spacing_{axis}", {"grid_spacing": f"{axis}_axis"})
                # (f"grid_spacing_{axis}", f"grid_spacing_{axis}")
            )
    setup_constants(
        obj_instance = controller_instance,
        attr_info = attr_info
    )

def setup_connect_constants(
    communicator_instance: Union[
        BaseCommunicator, SerialCommunicator, SocketCommunicator, 
        # WebsocketCommunicator
    ]
):
    """
    Scrape the hardware constants for the given communicator_instance.

    Add common attributes for hardware communications into the communicator config.
    Parameters
    ----------
    communicator_instance : _type_
        _description_
    """
    attr_info = [
        # (name, constants key)
        ("POLLINGDELAY", "pollingrate")
    ]
    if isinstance(communicator_instance, SerialCommunicator):
        attr_info.append(
            ("port", {"device_identifiers": "port"})
        )
        attr_info.append(
            ("device_identifiers", "device_identifiers")
        )
    elif isinstance(communicator_instance, SocketCommunicator):
        attr_info.append(
            ("ip", {"device_identifiers": "ip"})
        )
        attr_info.append(
            ("device_identifiers", "device_identifiers")
        )
        attr_info.append(
            ("_connected_network_devices", {})
        )
    #TODO: handle special cases
    # spec_attrs = []
    # if isinstance(communicator_instance, SerialCommunicator):
    #     # add special constants for the SerialCommunicator, if they have not yet been defined as attributes
    # elif isinstance(communicator_instance, SocketCommunicator):
    #     # add special constants for just the SocketCommunicator
    # elif isinstance(communicator_instance, WebsocketCommunicator):

    setup_constants(
        obj_instance = communicator_instance,
        attr_info = attr_info
    )
