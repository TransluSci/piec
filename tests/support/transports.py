"""Fake instrument communication used by the physical-driver tests."""

from typing import Dict, List, Optional


class ScriptedTransport:
    """Record writes and return configured query replies without hardware."""

    def __init__(self, responses: Optional[Dict[str, str]] = None,
                 address: str = "GPIB0::1::INSTR"):
        self.resource_name = address
        self.writes: List[str] = []
        self.responses = dict(responses or {})

    def write(self, command: str) -> None:
        self.writes.append(str(command).strip())

    def query(self, command: str) -> str:
        # Generic driver constructors may query status or numeric settings.
        return str(self.responses.get(str(command).strip(), "0"))

    def query_ascii_values(self, command: str, **kwargs) -> List[float]:
        return [float(value) for value in self.query(command).split(",") if value.strip()]

    def query_binary_values(self, command: str, **kwargs) -> List[float]:
        return self.query_ascii_values(command, **kwargs)

    def read(self) -> str:
        return ""

    def clear(self) -> None:
        pass

    def close(self) -> None:
        pass


def create_test_driver(driver_cls: type, responses: Optional[Dict[str, str]] = None,
                       check_params: bool = False):
    """Attach a fake transport and shared state, bypassing hardware initialization."""
    instance = driver_cls.__new__(driver_cls)
    instance.instrument = ScriptedTransport(responses=responses)
    instance._initialize_common_state(check_params=check_params, verbose=False)
    return instance
