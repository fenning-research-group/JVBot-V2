import serial.tools.list_ports as lp
import sys
from .base_config import BaseConstantsConfig
from typing import Tuple, List, Union

def which_os():
    if sys.platform.startswith("win"):
        return "Windows"
    elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
        # this excludes your current terminal "/dev/tty"
        return "Linux"
    elif sys.platform.startswith("darwin"):
        return "Darwin"
    else:
        raise EnvironmentError("Unsupported platform")


def _get_port_windows(device_identifiers):
    for p in lp.comports():
        match = True
        for attr, value in device_identifiers.items():
            if getattr(p, attr) != value:
                match = False
        if match:
            return p.device
    raise ValueError("Cannot find a matching port!")


def _get_port_linux(serial_number):
    """
    finds port number for a given hardware serial number
    """
    for p in lp.comports():
        if p.serial_number and p.serial_number == serial_number:
            return p.device
    return None


def get_port(device_identifiers):
    operatingsystem = which_os()
    if operatingsystem == "Windows":
        port = _get_port_windows(device_identifiers)
    elif operatingsystem == "Linux":
        port = _get_port_linux(device_identifiers["serialid"])

    if port is None:
        raise ValueError(f"Device not found!")
    return port



def setup_config(obj_instance, attr_info: List[Tuple[str, Union[str, dict, int, float, list]]]) -> None:
    """Scrape the hardware constants.
    
    Adds attrs from attr_info into the configuration of the provided obj_instance

    Parameters
    ----------
    obj_instance : Union[BaseMotionControl, BaseCommunicator, BaseControlKeithley]
    attr_info:
    """
    for ati in attr_info:
        name_, val_ = ati
        if isinstance(val_, dict):
            if "device_identifiers" == name_:
                val = {k: obj_instance._constants[k][v] for k, v in val_.items()}
            elif ("grid_spacing" in name_) or ("ip" in name_):
                vd = {k: obj_instance._constants[k][v] for k, v in val_.items()}
                vv = [v for _, v in vd.items()][0]
                val = vv
            elif ("_" in name_) and (not val_):
                val = {k: obj_instance._constants[v] for k, v in val_.items()}
            elif ("_" in name_) and (val_) and ("FRAMES" not in name_):
                val = {}
            elif ("FRAMES" in name_):
                val = {k: obj_instance._constants[v] for k, v in val_.items()}
            else:
                val = {k: obj_instance._constants[k][v] for k, v in val_.items()}
        elif isinstance(val_, str):
            val = obj_instance._constants[val_]
        else:
            val = val_
        setattr(
            obj_instance._config,
            name_,
            val,
        )