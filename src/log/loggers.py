import logging
import os
import sys
import pathlib
from datetime import datetime
from functools import wraps
from typing import Callable, Union, Generator, Optional, Tuple
from zoneinfo import ZoneInfo

from frozendict import frozendict

import numpy as np


from src.log.terminal_consts import LOGGING_LEVELS, ANSI_COLORS, ANSI_COLORED_TERMINAL_LOGGING_LEVELS, TERMINAL_RESET


_MODULE_CONSTS = frozendict(RUNTIME_LOGS_PATH=f"{pathlib.Path().resolve()}/runtime_logs",
                            safe_symbols_table=frozendict({"/": ".", ":": "-", "\\": ".", "*": "'", "|": "--"}))


class EndpointLogger:
    def debug(self, msg: str): raise NotImplementedError()
    def test(self, msg: str): pass
    def note(self, msg: str): pass
    def external(self, msg: str): pass
    def notify(self, msg: str): pass
    def info(self, msg: str): raise NotImplementedError()
    def dump(self, msg: Union[str, bytes, np.ndarray], max_length: int = -1): pass
    def core(self, msg: str): pass
    def system(self, msg: str): pass
    def warning(self, msg: str): raise NotImplementedError()
    def attention(self, msg: str, trace: bool = False): pass
    def exception(self, msg: str, trace: bool = False): raise NotImplementedError()
    def error(self, msg: str, trace: bool = True): raise NotImplementedError()
    def critical(self, msg: str): raise NotImplementedError()
    def panic(self, msg: str, trace: bool = True): pass
    def fatal(self, msg: str, trace: bool = True): raise NotImplementedError()
    @property
    def detetime_fmt(self) -> str: raise NotImplementedError()
    @property
    def detetime_timezone(self) -> str: raise NotImplementedError()
    @classmethod
    def now_with_timezone(cls, timezone: str) -> datetime: raise NotImplementedError()
    def now(self) -> datetime: raise NotImplementedError()
    def strftime(self, dt: datetime) -> str: raise NotImplementedError()
    def strftime_now(self, safe_format: bool = False) -> str: raise NotImplementedError()

    @classmethod
    def cut_sequence(cls, sequence: Union[str, bytes, np.ndarray], stay_len: int = 8, stay_at_end: bool = True, length_prefix: bool = False) -> str:
        raise NotImplementedError()


class MiddlewareLogger(EndpointLogger):
    def __init__(self, detetime_fmt: str, timezone: str):
        self._detetime_fmt = detetime_fmt
        self._datetime_timezone = timezone

    @property
    def detetime_fmt(self) -> str:
        return self._detetime_fmt

    @property
    def detetime_timezone(self) -> str:
        return self._datetime_timezone

    @classmethod
    def now_with_timezone(cls, timezone: str = "UTC") -> datetime:
        return datetime.now(ZoneInfo(timezone))

    def now(self) -> datetime:
        return self.now_with_timezone(self.detetime_timezone)

    def strftime(self, dt: datetime) -> str:
        return dt.strftime(self.detetime_fmt)

    def strftime_now(self, safe_format: bool = False) -> str:
        result = self.strftime(self.now())
        if safe_format:
            for s, r in _MODULE_CONSTS["safe_symbols_table"].items():
                result = result.replace(s, r)
        return result

    @classmethod
    def cut_sequence(cls, sequence: Union[str, bytes, np.ndarray], stay_len: int = 8, stay_at_end: bool = True, length_prefix: bool = False) -> str:
        prefix: str = f"[{f'[Length={len(sequence)}]'}" if length_prefix else ""
        if len(sequence) < stay_len * 2:
            return f"{prefix}{sequence}"
        else:
            return f"{prefix}{sequence[0:stay_len]}...{sequence[len(sequence) - stay_len:] if stay_at_end else ""}"


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

    def _message_out(self, message: str) -> None:
        self.io(f"[{self.id}] {message}")

    @check_io
    def msg(self, message: str) -> None:
        self._message_out(message)

    @check_io
    def msg_lazy(self, func: Callable[[], str]) -> None:
        self._message_out(func())

    @check_io
    def msg_frame_no(self, frame_no: int, message: str) -> None:
        self._message_out(f"[Frame={frame_no}] {message}")

    @check_io
    def msg_lazy_frame_no(self, frame_no: int, func: Callable[[], str]) -> None:
        self.msg_frame_no(frame_no, func())

    def stream_msgs_block_gen(self, frame_no: int) -> Generator[Optional[bool], Tuple[str, str], None]:
        if self.io is None:
            yield False
        while True:
            received_descr, received_result = yield
            self.msg_frame_no(frame_no, f"{received_descr}: {MiddlewareLogger.cut_sequence(received_result, length_prefix=True)} {MiddlewareLogger.cut_sequence(received_result, 92, length_prefix=True)}")


class DefaultLogger(MiddlewareLogger):
    def __init__(self, detetime_fmt: str, timezone: str, logger_name: str, log_fmt: str):
        super().__init__(detetime_fmt, timezone)
        os.makedirs(_MODULE_CONSTS["RUNTIME_LOGS_PATH"], exist_ok=True)
        logger_file_path = f"{_MODULE_CONSTS["RUNTIME_LOGS_PATH"]}/{logger_name}_{self.strftime_now(safe_format=True)}.log"
        logging.basicConfig(
            level=logging.DEBUG,
            datefmt=detetime_fmt,
            format=log_fmt,
            handlers=[logging.FileHandler(logger_file_path, encoding='utf-8'), logging.StreamHandler(sys.stdout)]
        )
        self.logger = logging.getLogger(logger_name)

    def debug(self, msg: str): self.logger.debug(msg)
    def test(self, msg: str): self.logger.critical(f"[TEST] {msg}")
    def note(self, msg: str): self.logger.critical(f"[NOTE] {msg}")
    def external(self, msg: str): self.logger.critical(f"[EXTERNAL] {msg}")
    def notify(self, msg: str): self.logger.critical(f"[NOTIFY] {msg}")
    def exception(self, msg: str, trace: bool = False): self.logger.exception(msg)
    def info(self, msg: str): self.logger.info(msg)
    def error(self, msg: str, trace: bool = True): self.logger.error(msg)
    def critical(self, msg: str, trace: bool = True): self.logger.critical(msg)
    def core(self, msg: str, trace: bool = True): self.logger.critical(f"[CORE] {msg}")
    def system(self, msg: str, trace: bool = True): self.logger.critical(f"[SYSTEM] {msg}")
    def warning(self, msg: str, trace: bool = True): self.logger.warning(msg)
    def fatal(self, msg: str, trace: bool = True): self.logger.fatal(msg)


class ColoredStreamHandler(logging.StreamHandler):

    def __init__(self, stream=None):
        super().__init__(stream=stream or sys.stdout)
    def format(self, record):
        original_msg = super().format(record)
        log_level_name = LOGGING_LEVELS.v_get(record.levelno.real)
        log_level_colour_name = ANSI_COLORED_TERMINAL_LOGGING_LEVELS.get(log_level_name)
        log_level_colour_code = ANSI_COLORS.get(log_level_colour_name)
        return f"{log_level_colour_code}{original_msg}{TERMINAL_RESET}"


class ExtendedLevelsLogger(MiddlewareLogger):
    def __init__(self, detetime_fmt: str, timezone: str, logger_name: str, log_fmt: str):
        super().__init__(detetime_fmt, timezone)
        for name, value in LOGGING_LEVELS.items():
            logging.addLevelName(value, name.upper())

        os.makedirs(_MODULE_CONSTS["RUNTIME_LOGS_PATH"], exist_ok=True)
        logger_file_path = f"{_MODULE_CONSTS["RUNTIME_LOGS_PATH"]}/{logger_name}_{self.strftime_now(safe_format=True)}.log"

        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(1)
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        formatter = logging.Formatter(
            fmt=log_fmt,
            datefmt=detetime_fmt
        )
        for handler in (logging.FileHandler(logger_file_path, encoding='utf-8'), ColoredStreamHandler(sys.stdout)):
            handler.setFormatter(formatter)
            handler.setLevel(1)
            self.logger.addHandler(handler)

    def _log(self, level_name: str, message: str, is_exception: bool = False):
        level_value = LOGGING_LEVELS.get(level_name)
        self.logger.log(level_value, message, exc_info=is_exception, stacklevel=3)

    def debug(self, msg: str): self._log('debug', msg)
    def test(self, msg: str): self._log('test', msg)
    def note(self, msg: str): self._log('note', msg)
    def external(self, msg: str): self._log('external', msg)
    def notify(self, msg: str): self._log('notify', msg)
    def info(self, msg: str): self._log('info', msg)
    def dump(self, msg: Union[str, bytes, np.ndarray], max_length: int = -1): self._log('dump', msg if max_length < 1 else self.cut_sequence(msg, max_length, length_prefix=True))
    def core(self, msg: str): self._log('core', msg)
    def system(self, msg: str): self._log('system', msg)
    def warning(self, msg: str): self._log('warning', msg)
    def attention(self, msg: str, trace: bool = False): self._log('attention', msg, is_exception=trace)
    def exception(self, msg: str, trace: bool = False): self._log('exception', msg, is_exception=trace)
    def error(self, msg: str, trace: bool = True): self._log('error', msg, is_exception=trace)
    def critical(self, msg: str, trace: bool = True): self._log('critical', msg, is_exception=trace)
    def panic(self, msg: str, trace: bool = True): self._log('panic', msg, is_exception=trace)
    def fatal(self, msg: str, trace: bool = True): self._log('fatal', msg, is_exception=trace)

    def visualize(self, msg: str = "Testing log levels colour scheme!"):
        for log_level_name in LOGGING_LEVELS.keys():
            self._log(log_level_name, msg)
