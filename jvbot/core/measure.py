from abc import ABC, abstractmethod

class BaseExecutor(ABC):
    @abstractmethod
    def setup_hardware(self, config, instrument):
        """Configure the compliance limits, source modes, and other settings before execution of a measurement."""
        pass

    @abstractmethod
    def run_measurement(self, config, instrument) -> dict:
        """The code measurement logic."""
        pass

    @abstractmethod
    def teardown_hardware(self, config, instrument):
        """Safely power down source, disable outputs, and restore defaults."""
        pass

    def execute(self, config, instrument) -> dict:
        """The main orchestration engine for one measurement."""
        self.setup_hardware(config, instrument)
        try:
            data = self.run_measurement(config, instrument)
            return data
        finally:
            self.teardown_hardware(config, instrument)