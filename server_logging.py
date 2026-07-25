from functools import wraps
from typing import Callable, Union, Generator, Optional, Tuple

import numpy as np


def check_io(f):
    @wraps(f)
    def decorated_function(self, *args, **kwargs):
        if not self.io:
            return
        return f(self, *args, **kwargs)
    return decorated_function


class SimpleDebugOnlyLogger:
    def __init__(self, id: str, io: Callable[[str, ...], None] = None):
        self.id = id
        self.io = io

    def __message_out(self, message) -> None:
        self.io(f"[{self.id}] {message}")

    @check_io
    def msg(self, message: str) -> None:
        self.__message_out(message)

    @check_io
    def msg_lazy(self, func: Callable[[], str]) -> None:
        self.__message_out(func())

    @check_io
    def msg_frame_no(self, frame_no: int, message: str) -> None:
        self.__message_out(f"[Frame={frame_no}] {message}")

    @check_io
    def msg_lazy_frame_no(self, frame_no: int, func: Callable[[], str]) -> None:
        self.msg_frame_no(frame_no, func())

    def stream_msgs_block_gen(self, frame_no: int) -> Generator[Optional[bool], Tuple[str, str], None]:
        if self.io is None:
            yield False
        while True:
            received_descr, received_result = yield
            self.msg_frame_no(frame_no, f"{received_descr}: {self.cut_seq_with_prefix(received_result, 92)}")

    def cut_seq_with_prefix(self, data: Union[str, bytes], stay_len: int = 8, stay_at_end: bool = True) -> str:
        return f"[{f'[Length={len(data)}]'} {self.cut_seq(data, stay_len, stay_at_end)}"

    def cut_seq(self, data: Union[str, bytes, np.ndarray], stay_len: int = 8, stay_at_end: bool = True) -> str:
        if len(data) < stay_len * 2:
            return f"{data}"
        else:
            return f"{data[0:stay_len]}...{data[len(data) - stay_len:] if stay_at_end else ""}"
