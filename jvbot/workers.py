import asyncio
import logging
from collections import namedtuple
from roboflo import Worker as Worker_roboflo
import os
import sys

task_tuple = namedtuple("task", ["function", "estimated_duration", "other_workers"])


class WorkerTemplate(Worker_roboflo):
    def __init__(self, name, capacity, maestro=None, planning=False, initial_fill=0):
        self.name = name
        self.capacity = capacity
        self.maestro = maestro
        self.working = False
        self.logger = logging.getLogger("JVBot")
        super().__init__(name=name, capacity=capacity)

    def prime(self, loop):
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.queue = asyncio.PriorityQueue()
        # self.setup_logger(self.name)

    def setup_logger(self, logger_name):
        self.worker_logger = logging.getLogger(logger_name)
        self.worker_logger.setLevel(logging.DEBUG)
        
        if self.maestro and hasattr(self.maestro, "experiment_folder"):
            if not self.worker_logger.handlers:
                worker_logs_dir = os.path.join(self.maestro.experiment_folder, "worker_logs")
                os.makedirs(worker_logs_dir, exist_ok=True)
                
                fh = logging.FileHandler(
                    os.path.join(worker_logs_dir, f"{logger_name}.log")
                )
                sh = logging.StreamHandler(sys.stdout)
                sh.setLevel(logging.INFO)
                
                fh_formatter = logging.Formatter(
                    "%(asctime)s %(levelname)s: %(message)s",
                    datefmt="%m/%d/%Y %I:%M:%S %p",
                )
                sh_formatter = logging.Formatter(
                    "%(asctime)s %(message)s",
                    datefmt="%I:%M:%S",
                )
                fh.setFormatter(fh_formatter)
                sh.setFormatter(sh_formatter)
                
                self.worker_logger.addHandler(fh)
                self.worker_logger.addHandler(sh)

    def start(self):
        def future_callback(future):
            try:
                future.result()
            except Exception as e:
                self.logger.exception(f"Exception in {self}")
                # if future.exception(): #your long thing had an exception
                #     self.logger.error(f'Exception in {self}: {future.exception()}')

        self.working = True
        for _ in range(self.capacity):
            future = asyncio.run_coroutine_threadsafe(self.worker(), self.loop)
            future.add_done_callback(future_callback)

    def stop_workers(self):
        self.working = False

    def add_task(self, task):
        # payload = (task["start"], task)
        # self.loop.call_soon_threadsafe(self.queue.put_nowait, payload)
        payload = (task["start"], task)
        self.loop.call_soon_threadsafe(self.queue.put_nowait, payload)

    async def worker(self):
        """process items from the queue + keep the maestro lists updated"""

        def future_callback(future):
            try:
                future.result()
            except Exception as e:
                self.logger.exception(f"Exception in {self}")

        while self.working:
            while True:
                if len(self.queue._queue) > 0:
                    time_until_next = (
                        self.queue._queue[0][0] - self.maestro.experiment_time
                    )  # seconds until task is due

                    if time_until_next <= 1:  # within 1 second of start time
                        break
                await asyncio.sleep(0.2)

            _, task = await self.queue.get()  # blocking wait for next task
            task_description = f'{task["name"]}, {task["sample"]}'
            sample = self.maestro.samples[task["sample"]]
            sample_task = [t for t in sample["worklist"] if t["id"] == task["id"]][0]
            if task is None:  # finished flag
                break

            with self.maestro.lock_pendingtasks:
                self.maestro.pending_tasks.append(task["id"])

            if task["precedent"] is not None:
                first = True
                found = False
                while not found:
                    with self.maestro.lock_completedtasks:
                        found = task["precedent"] in self.maestro.completed_tasks
                    if found:
                        break
                    else:
                        if first:
                            msg_prec = f"waiting for precedents of {task_description}"
                            self.logger.info(msg_prec)
                            if hasattr(self, "worker_logger") and self.worker_logger:
                                self.worker_logger.info(msg_prec)
                        await asyncio.sleep(self.POLLINGRATE)
                        first = False

            # wait for this task's target start time
            wait_for = task["start"] - (self.maestro.experiment_time)
            if wait_for > 0:
                msg_wait = f"waiting {wait_for:.2f} seconds for {task_description} start time"
                self.logger.info(msg_wait)
                if hasattr(self, "worker_logger") and self.worker_logger:
                    self.worker_logger.info(msg_wait)
                await asyncio.sleep(wait_for)

            # execute this task
            sample_task["start_actual"] = self.maestro.experiment_time
            function = self.functions[task["name"]].function
            details = sample_task.get("details", {})
            details["task_id"] = task["id"]

            details_summary = ", ".join([f"{k}={v}" for k, v in details.items() if k not in ["task_id", "ot2_settings", "drops", "steps", "mixing_netlist"]])
            msg_start = f"Started task '{task['name']}'"
            if details_summary:
                msg_start += f" ({details_summary})"
            self.logger.info(f"executing {task_description}")
            if hasattr(self, "worker_logger") and self.worker_logger:
                self.worker_logger.info(f"[START] {msg_start}")
            self.maestro.log_sample_event(sample["name"], msg_start)

            try:
                if asyncio.iscoroutinefunction(function):
                    output_dict = await function(sample, details)
                else:
                    future = asyncio.gather(
                        self.loop.run_in_executor(
                            self.maestro.threadpool,
                            function,
                            sample,
                            details,
                        )
                    )
                    future.add_done_callback(future_callback)
                    output_dict = await future
                    output_dict = output_dict[0]
                
                if output_dict is None:
                    output_dict = {}
                output_dict["status"] = "success"

                msg_finish = f"Finished task '{task['name']}'"
                if hasattr(self, "worker_logger") and self.worker_logger:
                    self.worker_logger.info(f"[FINISHED] {msg_finish}")
                self.maestro.log_sample_event(sample["name"], msg_finish)

            except Exception as e:
                self.logger.exception(f"Exception in task {task_description}")
                err_msg = f"Failed task '{task['name']}' with error: {e}"
                if hasattr(self, "worker_logger") and self.worker_logger:
                    self.worker_logger.error(f"[ERROR] {err_msg}")
                self.maestro.log_sample_event(sample["name"], err_msg)
                output_dict = {"status": "error", "error": str(e)}

            if output_dict is None:
                output_dict = {}
            # update task lists
            output_dict["finish_actual"] = self.maestro.experiment_time
            sample_task.update(output_dict)

            self.logger.info(f"finished {task_description}")
            with self.maestro.lock_completedtasks:
                self.maestro.completed_tasks[task["id"]] = self.maestro.experiment_time
            with self.maestro.lock_pendingtasks:
                self.maestro.pending_tasks.remove(task["id"])
            self.queue.task_done()

    def __hash__(self):
        return hash(str(type(self)))


class Worker_Gantry(WorkerTemplate):
    def __init__(self, maestro=None, planning=False):
        super().__init__(name="Gantry", maestro=maestro, planning=planning, capacity=1)
        self.functions = {
            "moveto": task_tuple(
                function=self.moveto,
                estimated_duration=5,
                other_workers=[Worker_Measurement],
            ),
            "gohome": task_tuple(
                function=self.gohome,
                estimated_duration=10,
                other_workers=[Worker_Measurement],
            ),
        }

    def moveto(self, sample, details):
        pass

    def gohome(self, sample, details):
        pass


class Worker_Measurement(WorkerTemplate):
    def __init__(self, maestro=None, planning=False):
        super().__init__(name="Measurement", maestro=maestro, planning=planning, capacity=1)
        self.functions = {
            "jv_sweep": task_tuple(
                function=self.jv_sweep,
                estimated_duration=5,
                other_workers=[Worker_Gantry],
            ),
            "voc_direct": task_tuple(
                function=self.voc_direct,
                estimated_duration=5,
                other_workers=[Worker_Gantry],
            ),
            "voc_buffered": task_tuple(
                function=self.voc_buffered,
                estimated_duration=5,
                other_workers=[Worker_Gantry],
            ),
            "jsc_direct": task_tuple(
                function=self.jsc_direct,
                estimated_duration=5,
                other_workers=[Worker_Gantry],
            ),
            "jsc_buffered": task_tuple(
                function=self.jsc_buffered,
                estimated_duration=5,
                other_workers=[Worker_Gantry],
            ),
            "spo_buffered": task_tuple(
                function=self.spo_buffered,
                estimated_duration=5,
                other_workers=[Worker_Gantry],
            ),
        }

    def jv_sweep(self, sample, details):
        pass

    def voc_direct(self, sample, details):
        pass

    def voc_buffered(self, sample, details):
        pass

    def jsc_direct(self, sample, details):
        pass

    def jsc_buffered(self, sample, details):
        pass

    def spo_buffered(self, sample, details):
        pass


class Worker_SolarSim(WorkerTemplate):
    def __init__(self, maestro=None, planning=False):
        super().__init__(name="SolarSim", maestro=maestro, planning=planning, capacity=1)
        self.functions = {
            "set_intensity": task_tuple(
                function=self.set_intensity,
                estimated_duration=3,
                other_workers=[Worker_Measurement],
            ),
            "turn_on": task_tuple(
                function=self.turn_on,
                estimated_duration=2,
                other_workers=[Worker_Measurement],
            ),
            "turn_off": task_tuple(
                function=self.turn_off,
                estimated_duration=2,
                other_workers=[Worker_Measurement],
            ),
        }

    def set_intensity(self, sample, details):
        pass

    def turn_on(self, sample, details):
        pass

    def turn_off(self, sample, details):
        pass
