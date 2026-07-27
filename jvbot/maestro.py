import os
import sys
import time
import asyncio
import logging
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor
# pyrefly: ignore [missing-import]
import ntplib
from warnings import warn
import datetime
import json
import yaml

from jvbot.workers import Worker_Gantry, Worker_Measurement, Worker_SolarSim

MODULE_DIR = os.path.dirname(__file__)
with open(os.path.join(MODULE_DIR, "hardware", "hardwareconstants.yaml"), "r") as f:
    constants = yaml.load(f, Loader=yaml.FullLoader)

ROOTDIR = "C:\\Users\\Admin\\Desktop\\JVBot_Runs" # change? no clue

class Maestro:
    def __init__(
        self,
        gantry=None,
        instrument=None,
        solarsim=None,
        tray=None,
        experiment_folder=".",
    ):
        self.logger = logging.getLogger("JVBot")
        self.experiment_folder = experiment_folder
        self.constants = constants
        
        # Hardware references
        if gantry is None:
            try:
                from jvbot.hardware.old_gantry import Gantry
                gantry = Gantry()
            except Exception as e:
                print(f"maestro: could not automatically connect to gantry: {e}")
        self.gantry = gantry

        if instrument is None:
            try:
                from jvbot.hardware.control5_legacy import Control_Keithley_Eric as KeithleyControl
                addr = constants["keithley"]["address"]
                instrument = KeithleyControl(area=0.048, address=addr)
            except Exception as e:
                print(f"maestro: could not automatically connect to keithley: {e}")
        self.instrument = instrument
        self.control_keithley = instrument  

        self.solarsim = solarsim

        if tray is None and self.gantry is not None:
            try:
                from jvbot.hardware.new_tray import Tray10mm
                tray = Tray10mm(version="tray_v1", gantry=self.gantry)
            except Exception as e:
                print(f"maestro: could not automatically load tray: {e}")
        self.tray = tray

        self.threadpool = ThreadPoolExecutor(max_workers=40)

        # Status
        self.samples = {}
        self.tasks = []
        self.lock_pendingtasks = Lock()
        self.lock_completedtasks = Lock()
        self.t0 = None
        self._under_external_control = False

        # Logger
        self.logger = logging.getLogger("JVBot")

        # Time Synchronization with NIST
        self.__calibrate_time_to_nist()

        # Workers instantiation
        self.workers = {
            "gantry": Worker_Gantry(maestro=self),
            "measurement": Worker_Measurement(maestro=self),
            "solarsim": Worker_SolarSim(maestro=self),
        }

    ### Time Synchronization with NIST
    def __calibrate_time_to_nist(self):
        client = ntplib.NTPClient()
        response = None
        t0 = time.time()
        while response is None:
            try:
                response = client.request("europe.pool.ntp.org", version=3)
            except Exception as e:
                print(f"nist time sync try failed: {e}")
                pass
            if time.time() - t0 >= 10:
                warn("Could not get NIST time!")
                return
        self.__local_nist_offset = response.tx_time - time.time()
        print(f"nist time calibrated. offset is {self.__local_nist_offset} seconds")

    @property
    def experiment_time(self):
        if self.t0 is None:
            raise Exception("Experiment has not started!")
        return self.nist_time - self.t0

    @property
    def nist_time(self):
        return time.time() + self.__local_nist_offset

    def make_background_event_loop(self):
        def exception_handler(loop, context):
            print("Exception raised in Maestro loop")
            print(f"loop exception context: {context}")
            self.logger.error(json.dumps(context))

        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(exception_handler)
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._keep_loop_running())

    async def _keep_loop_running(self):
        experiment_started = False
        experiment_completed = False
        if self._under_external_control:
            # if under external control, the pending tasklist might be exhausted before experiment ends
            while self.working:
                await asyncio.sleep(1)
            # once we manually set `self.working = False`, wait for pending tasks to be exhausted
            while len(self.pending_tasks) > 0:
                await asyncio.sleep(1)
            experiment_completed = True
        else:
            # if under maestro control, experiment is done when the tasklist is exhausted!
            while self.working:
                if (
                    not experiment_started
                ):  # wait for the task list to start being populated
                    with self.lock_pendingtasks:
                        if len(self.pending_tasks) > 0:
                            experiment_started = True
                    await asyncio.sleep(30)
                elif not experiment_completed:
                    with self.lock_pendingtasks:
                        if len(self.completed_tasks) == len(self.tasks):
                            experiment_completed = True
                    await asyncio.sleep(5)
                else:
                    break
        if experiment_completed == True:
            self.stop()

    def _start_loop(self):
        self.working = True
        self.thread = Thread(target=self.make_background_event_loop)
        self.thread.start()  # generates asyncio event loop in background thread (self.loop)
        time.sleep(0.5)
        # self.loop = asyncio.new_event_loop()
        # self.loop.set_debug(True)
    
    def _load_worklist(self, filepath):
        print(f"loading worklist file: {filepath}")
        try:
            with open(filepath, "r") as f:
                worklist = json.load(f)
        except Exception as e:
            print(f"failed to read or parse worklist json: {e}")
            raise e
        # self.tasks = worklist["tasks"]
        self.samples = worklist["samples"]
        self.tasks = []
        for details in self.samples.values():
            self.tasks.extend(details["worklist"])
        self.tasks.sort(key=lambda t: t["start"])

        return worklist["name"]
        # self._characterization_baselines_required = worklist["baselines_required"]

    def _set_up_experiment_folder(self, name):
        todays_date = datetime.datetime.now().strftime("%Y%m%d")
        folder_name = f"{todays_date}_{name}"
        suffix = ""
        idx = 0
        while True:
            folder = os.path.join(ROOTDIR, f"{folder_name}{suffix}")
            if os.path.exists(folder):
                idx += 1
                suffix = f"_{idx}"
            else:
                break
        print(f"creating experiment folder at: {folder}")
        try:
            os.mkdir(folder)
            print(f"Experiment folder created at {folder}")
        except Exception as e:
            print(f"failed to create experiment folder {folder}: {e}")
            raise e

        self.experiment_folder = folder
        self.logger.setLevel(logging.DEBUG)
        self._fh = logging.FileHandler(
            os.path.join(self.experiment_folder, f"{folder_name}.log")
        )
        self._sh = logging.StreamHandler(sys.stdout)
        self._sh.setLevel(logging.INFO)
        fh_formatter = logging.Formatter(
            "%(asctime)s %(levelname)s: %(message)s",
            datefmt="%m/%d/%Y %I:%M:%S %p",
        )
        sh_formatter = logging.Formatter(
            "%(asctime)s %(message)s",
            datefmt="%I:%M:%S",
        )
        self._fh.setFormatter(fh_formatter)
        self._sh.setFormatter(sh_formatter)
        self.logger.addHandler(self._fh)
        self.logger.addHandler(self._sh)

        return folder

    def load_netlist(self, filepath: str):
        experiment_name = self._load_worklist(filepath)
        self._set_up_experiment_folder(experiment_name)

    def _experiment_checklist(self):
        pass

    def run(self):
        print("running experiment checklist...")
        try:
            self._experiment_checklist()
        except Exception as e:
            print(f"experiment checklist failed: {e}")
            raise e
        self.pending_tasks = []
        self.completed_tasks = {}

        print("starting background event loop...")
        self._start_loop()
        try:
            self.t0 = self.nist_time
            print(f"experiment started. t0 set to {self.t0}")
        except Exception as e:
            print(f"failed to get nist time for t0: {e}")
            raise e

        for name, worker in self.workers.items():
            print(f"priming worker: {name}")
            try:
                worker.prime(loop=self.loop)
            except Exception as e:
                print(f"failed to prime worker {name}: {e}")
                raise e
        for task in self.tasks:
            assigned = False
            for workername, worker in self.workers.items():
                if task["name"] in worker.functions:
                    print(f"assigning task {task['name']} for sample {task['sample']} to worker {workername}")
                    worker.add_task(task)
                    assigned = True
                    continue
            if not assigned:
                print(f"error: no worker has task {task['name']} in functions list")
                raise Exception(f"No worker assigned to task {task['name']}")

        for name, worker in self.workers.items():
            print(f"starting worker: {name}")
            try:
                worker.start()
            except Exception as e:
                print(f"failed to start worker {name}: {e}")
                raise e

    def move_to_slot(self, slot):
        """Move the gantry probe head to the specified sample slot on the tray."""
        if self.tray is None:
            print("warning: move_to_slot failed because tray is not configured (self.tray is None)")
        if self.gantry is None:
            print("warning: move_to_slot failed because gantry is not configured (self.gantry is None)")
        if self.tray is not None and self.gantry is not None:
            print(f"resolving coordinates for slot {slot}...")
            try:
                coords = self.tray(slot)
                print(f"resolved slot {slot} coordinates to: {coords}")
            except Exception as e:
                print(f"failed to get coordinates for slot {slot} from tray: {e}")
                raise e
            self.logger.info(f"Moving probe head to slot '{slot}' (coords: {coords})")
            print(f"gantry moving to coords: {coords}")
            try:
                self.gantry.moveto(*coords)
                print(f"gantry move to {slot} completed successfully")
            except Exception as e:
                print(f"gantry move to coords {coords} failed: {e}")
                raise e
        else:
            self.logger.warning(f"Gantry or Tray not configured. Cannot move to slot '{slot}'.")

    def stop(self):
        print('Beginning to stop JVBot')
        self.working = False
        
        for name, w in self.workers.items():
            print(f"Stopping worker {name} now")
            try:
                w.stop_workers()
                print(f"\tStop Successful for {name}!")
            except Exception as e:
                print(f"failed to stop worker {name}: {e}")
