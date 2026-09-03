import logging
import os
import sys
from datetime import datetime
from functools import wraps
from typing import Callable, Union, Generator, Optional, Tuple

import numpy as np

from server_private import EndpointPrivateData

_RUNTIME_LOGS_PATH = "./runtime_logs"



class EndpointLogger:
    def debug(self, str):
        raise NotImplemented()
    def exception(self, str):
        raise NotImplemented()
    def info(self, str):
        raise NotImplemented()
    def error(self, str):
        raise NotImplemented()
    def critical(self, str):
        raise NotImplemented()
    def core(self, str):
        raise NotImplemented()
    def warning(self, str):
        raise NotImplemented()


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


class DefaultLogger(EndpointLogger):
    def __init__(self, private_config: EndpointPrivateData):
        os.makedirs(_RUNTIME_LOGS_PATH, exist_ok=True)
        log_filename = datetime.now().strftime(private_config.detetime_fmt).replace(":", "-")
        logger_file_path = f"{_RUNTIME_LOGS_PATH}/{private_config.logger_name}_{log_filename}.log"
        logging.basicConfig(
            level=logging.DEBUG,
            datefmt=private_config.detetime_fmt,
            format=private_config.log_fmt,
            handlers=[logging.FileHandler(logger_file_path, encoding='utf-8'), logging.StreamHandler(sys.stdout)]
        )
        self.logger = logging.getLogger(private_config.logger_name)

    def debug(self, msg: str):
        self.logger.debug(msg)

    def exception(self, msg: str):
        self.logger.exception(msg)

    def info(self, msg: str):
        self.logger.info(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def critical(self, msg: str):
        self.logger.critical(msg)

    def core(self, msg: str):
        self.logger.critical(f"[CORE]{msg}")

    def warning(self, msg: str):
        self.logger.warning(msg)

