import threading
import uuid
import inspect
from functools import wraps
from typing import Callable, Dict, Union, Optional
from datetime import timedelta

from server_logging import EndpointLogger
from server_streaming import AsyncAudioStream


def with_mutex(mutex_name: str):
    def factory(f):
        @wraps(f)
        def mutex_function(self, *args, **kwargs):
            if mutex := getattr(self, mutex_name, None):
                with mutex:
                    return f(self, *args, **kwargs)
        return mutex_function
    return factory


class StreamsStorage:
    def __init__(self, clear_interval: timedelta, stream_lifetime: timedelta, logger: EndpointLogger):
        self._storage_id: str = uuid.uuid4().hex
        self._logger = logger
        self._clear_interval: float = clear_interval.total_seconds()
        self._stream_lifetime: timedelta = stream_lifetime
        self._stop_event = threading.Event()
        self._mutex = threading.Lock()
        self._thread: threading.Thread = None
        self._streams_storage: Dict[str, AsyncAudioStream] = dict()

    @property
    def streams_count(self) -> int:
        return len(self._streams_storage)

    @property
    def mutex(self) -> threading.Lock:
        return self._mutex

    @property
    def storage_uuid(self) -> str:
        return self._storage_id

    @property
    def is_running(self) -> bool:
        return self._thread.is_alive() if self._thread else False

    @with_mutex("mutex")
    def clear_by_dt(self, dt: timedelta = timedelta(seconds=3)) -> None:
        self.___cleaner(dt)

    @with_mutex("mutex")
    def clear_by_filter(self, filter_func: Callable[[AsyncAudioStream], bool]) -> None:
        for key in list(self._streams_storage.keys()):
            if filter_func(self._streams_storage[key]):
                del self._streams_storage[key]

    def start(self) -> Optional[bool]:
        if self._thread is None:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self.__clear_worker)
            self._thread.daemon = True
            self._thread.start()
            return True

    def stop(self, wait_for_end: bool = False) -> Optional[bool]:
        if self.is_running:
           self._stop_event.set()
           if wait_for_end:
                self._thread.join()
           self._thread = None
        return True

    @with_mutex("mutex")
    def get_stream(self, session_uuid: str) -> Optional[AsyncAudioStream]:
        if stream := self._streams_storage.get(session_uuid):
            if stream.is_deprecated(self._stream_lifetime):
                del self._streams_storage[stream.stream_uuid]
            else:
                return stream

    @with_mutex("mutex")
    def add_stream(self, session_uuid: str, session: AsyncAudioStream, owerwrite: bool = True) -> None:
        if not owerwrite:
            if exists := self._streams_storage.get(session_uuid):
                raise ValueError(f"Stream with uuid: {session_uuid} already exists in storage!")
        self._streams_storage[session_uuid] = session

    def ___cleaner(self, dt: timedelta = None) -> None:
        real_lt: timedelta = dt if dt else self._stream_lifetime
        for key in list(self._streams_storage.keys()):
            self._logger.debug(f"{key} -> sg {inspect.getgeneratorstate(self._streams_storage[key].sample_gen)}, running: {self._streams_storage[key].status}", flush=True)
            if self._streams_storage[key].is_deprecated(real_lt):
                del self._streams_storage[key]
                self._logger.debug(f"Deleted {key}")

    def __clear_worker(self) -> None:
        while not self._stop_event.wait(self._clear_interval):
            with self._mutex:
                self.___cleaner()
