import threading
import uuid
import inspect
from functools import wraps
from typing import Callable, Dict, Union, Optional
from datetime import timedelta

from server_streaming import AsyncAudioStream


def with_mutex(f):
    @wraps(f)
    def mutex_function(self, *args, **kwargs):
        with self.mutex:
            return f(self, *args, **kwargs)
    return mutex_function


class StreamsStorage:
    def __init__(self, clear_interval: timedelta, stream_lifetime: timedelta):
        self.__storage_id: str = uuid.uuid4().hex
        self.__clear_interval: float = clear_interval.total_seconds()
        self.__stream_lifetime: timedelta = stream_lifetime
        self.__event = threading.Event()
        self.__mutex = threading.Lock()
        self.__thread: threading.Thread = None
        self.__streams_storage: Dict[str, AsyncAudioStream] = dict()

    @property
    @with_mutex
    def streams_count(self) -> int:
        return len(self.__streams_storage)

    @property
    def mutex(self) -> threading.Lock:

        return self.__mutex
    @property
    def storage_uuid(self) -> str:
        return self.__storage_id

    @property
    def is_running(self) -> bool:
        return self.__thread.is_alive() if self.__thread else False

    @with_mutex
    def clear_by_dt(self, dt: timedelta = timedelta(seconds=3)) -> None:
        self.___cleaner(dt)

    @with_mutex
    def clear_by_filter(self, filter_func: Callable[[AsyncAudioStream], bool]) -> None:
        for key in list(self.__streams_storage.keys()):
            if filter_func(self.__streams_storage[key]):
                del self.__streams_storage[key]

    def start(self) -> Optional[bool]:
        if self.__thread is None:
            self.__event.clear()
            self.__thread = threading.Thread(target=self.__clear_worker)
            self.__thread.daemon = True
            self.__thread.start()
            return True

    def stop(self, wait_for_end: bool = False) -> Optional[bool]:
        if self.is_running:
           self.__event.set()
           if wait_for_end:
                self.__thread.join()
           self.__thread = None
        return True

    @with_mutex
    def get_stream(self, session_uuid: str) -> Optional[AsyncAudioStream]:
        if stream := self.__streams_storage.get(session_uuid):
            if stream.is_deprecated(self.__stream_lifetime):
                del self.__streams_storage[stream.stream_uuid]
            else:
                return stream

    @with_mutex
    def add_stream(self, session_uuid: str, session: AsyncAudioStream, owerwrite: bool = True) -> None:
        if not owerwrite:
            if exists := self.__streams_storage.get(session_uuid):
                raise ValueError(f"Stream with uuid: {session_uuid} already exists in storage!")
        self.__streams_storage[session_uuid] = session

    def ___cleaner(self, dt: timedelta = None) -> None:
        real_lt: timedelta = dt if dt else self.__stream_lifetime
        for key in list(self.__streams_storage.keys()):
            print(f"{key} -> sg {inspect.getgeneratorstate(self.__streams_storage[key].sample_gen)}, running: {self.__streams_storage[key].status}", flush=True)
            if self.__streams_storage[key].is_deprecated(real_lt):
                del self.__streams_storage[key]
                print(f"deleted {key}", flush=True)

    def __clear_worker(self) -> None:
        while not self.__event.wait(self.__clear_interval):
            with self.__mutex:
                self.___cleaner()
