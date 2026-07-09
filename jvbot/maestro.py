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

from jvbot.workers import Worker_Gantry, Worker_Measurement, Worker_SolarSim

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
        
        # Hardware references
        self.gantry = gantry
        self.instrument = instrument
        self.control_keithley = instrument  
        self.solarsim = solarsim
        self.tray = tray # i think
        
        # Placeholders to prevent AttributeError
        self.hotplates = {}
        self.characterization = None

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
            except:
                pass
            if time.time() - t0 >= 10:
                warn("Could not get NIST time!")
                return
        self.__local_nist_offset = response.tx_time - time.time()

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
        with open(filepath, "r") as f:
            worklist = json.load(f)
        # self.tasks = worklist["tasks"]
        self.samples = worklist["samples"]
        self.tasks = []
        for details in self.samples.values():
            self.tasks.extend(details["worklist"])
        self.tasks.sort(key=lambda t: t["start"])

        for hp_name, temperature in worklist.get("hotplate_setpoints", {}).items():
            if hp_name in self.hotplates:
                self.hotplates[hp_name].controller.setpoint = temperature
                print(f"Hotplate {hp_name} set to {temperature:.1f}C")
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
        os.mkdir(folder)
        print(f"Experiment folder created at {folder}")

        if self.characterization is not None:
            self.characterization.set_directory(
                os.path.join(folder, "Characterization")
            )
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

    def _experiment_checklist(self):
        pass

    def run(self):
        self._experiment_checklist()
        self.pending_tasks = []
        self.completed_tasks = {}

        self._start_loop()
        self.t0 = self.nist_time

        for worker in self.workers.values():
            worker.prime(loop=self.loop)
        for task in self.tasks:
            assigned = False
            for workername, worker in self.workers.items():
                if task["name"] in worker.functions:
                    worker.add_task(task)
                    assigned = True
                    continue
            if not assigned:
                raise Exception(f"No worker assigned to task {task['name']}")

        for worker in self.workers.values():
            worker.start()

    def move_to_slot(self, slot):
        """Move the gantry probe head to the specified sample slot on the tray."""
        if self.tray is not None and self.gantry is not None:
            coords = self.tray(slot)
            self.logger.info(f"Moving probe head to slot '{slot}' (coords: {coords})")
            self.gantry.moveto(coords)
        else:
            self.logger.warning(f"Gantry or Tray not configured. Cannot move to slot '{slot}'.")

    def stop(self):
        print('Beginning to stop JVBot')
        self.working = False
        
        for w in self.workers.values():
            print(f"Stopping {w} now")
            w.stop_workers()
            print(f"\tStop Successful!")
