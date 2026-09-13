"""
Scripted fake VISA/vendor transport for testing physical drivers without hardware.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


class ScriptedTransport:
    """
    Fake VISA/vendor communication resource that records commands and serves scripted responses.
    """

    def __init__(
        self,
        responses: Optional[Dict[Union[str, re.Pattern], Any]] = None,
        address: str = "GPIB0::1::INSTR",
        error_on: Optional[Dict[str, Exception]] = None,
        strict: bool = False,
    ):
        self.resource_name = address
        self.writes: List[str] = []
        self.queries: List[Tuple[str, str]] = []
        self.responses: Dict[Union[str, re.Pattern], Any] = dict(responses or {})
        self.error_on: Dict[str, Exception] = dict(error_on or {})
        self.closed: bool = False
        self.cleared: bool = False
        self.strict = strict

    def write(self, command: str) -> None:
        cmd_str = str(command).strip()
        if cmd_str in self.error_on:
            raise self.error_on[cmd_str]
        self.writes.append(cmd_str)

    def query(self, query_str: str) -> str:
        q_str = str(query_str).strip()
        if q_str in self.error_on:
            raise self.error_on[q_str]

        # Exact match first
        if q_str in self.responses:
            reply = self.responses[q_str]
            if callable(reply):
                reply = reply(q_str)
            reply_str = str(reply)
            self.queries.append((q_str, reply_str))
            return reply_str

        # Pattern match
        for key, reply in self.responses.items():
            if isinstance(key, re.Pattern) and key.search(q_str):
                if callable(reply):
                    reply = reply(q_str)
                reply_str = str(reply)
                self.queries.append((q_str, reply_str))
                return reply_str

        # Default fallback query reply
        if self.strict:
            raise AssertionError(f"Unscripted instrument query: {q_str}")
        default_reply = "0"
        self.queries.append((q_str, default_reply))
        return default_reply

    def query_ascii_values(self, query_str: str, **kwargs) -> List[float]:
        resp = self.query(query_str)
        try:
            return [float(x.strip()) for x in resp.split(",") if x.strip()]
        except ValueError:
            if self.strict:
                raise
            return [0.0]

    def query_binary_values(self, query_str: str, **kwargs) -> List[float]:
        response = self.responses.get(query_str)
        if isinstance(response, (list, tuple, bytes, bytearray)):
            self.queries.append((query_str, repr(response)))
            return list(response)
        return self.query_ascii_values(query_str, **kwargs)

    def read(self) -> str:
        return ""

    def clear(self) -> None:
        self.cleared = True

    def close(self) -> None:
        self.closed = True


def create_test_driver(
    driver_cls: type,
    responses: Optional[Dict[Union[str, re.Pattern], Any]] = None,
    check_params: bool = False,
    address: str = "GPIB0::1::INSTR",
    protocol: Optional[str] = None,
    strict: bool = False,
    **kwargs,
) -> Any:
    """
    Construct a driver instance with a ScriptedTransport attached,
    bypassing physical hardware communication.
    """
    instance = driver_cls.__new__(driver_cls)
    transport = ScriptedTransport(responses=responses, address=address, strict=strict)
    instance.instrument = transport
    instance._initialize_common_state(check_params=check_params, verbose=False)
    if protocol is not None:
        instance._rigol_protocol = protocol
    for key, value in kwargs.items():
        setattr(instance, key, value)
    return instance
