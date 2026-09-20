import threading
from enum import Enum, auto, unique
from typing import Type

from server_logging import EndpointLogger
from server_private import InstanceThreadConfig
from server_queue import FixedTypedConcurrentDequeue, InternalQueuedItem
from server_storage import with_mutex


@unique
class ThreadState(Enum):
    ERROR_DOWN = auto()
    READY = auto()
    RUNNING = auto()
    FINALIZING = auto()
    FINALIZED = auto()
    PAUSED = auto()
    STOPPED = auto()


class IOQueuedThread(threading.Thread):
    def __init__(self, logger: EndpointLogger, config: InstanceThreadConfig):
        super().__init__(daemon=True)
        self._logger = logger
        self._name = config.instance_name
        self._node_config: InstanceThreadConfig = config
        self._output_queue: FixedTypedConcurrentDequeue[InternalQueuedItem] = FixedTypedConcurrentDequeue[InternalQueuedItem](logger, max_size=self._node_config.output_queue_max_size, name=f"{self.name}_output_dequeue")
        self._input_queue: FixedTypedConcurrentDequeue[InternalQueuedItem] = FixedTypedConcurrentDequeue[InternalQueuedItem](logger, max_size=self._node_config.output_queue_max_size, name=f"{self.name}_input_dequeue")
        self._mutex = threading.Lock()
        self._stop_signal = threading.Event()
        self._thread_state: ThreadState = ThreadState.READY

    @classmethod
    def from_another(cls, other_thread: Type["cls"]):
        return cls(other_thread._logger, other_thread.config)

    @property
    def name(self) -> str:
        return self._name

    @property
    def _state(self):
        return self._thread_state

    @_state.setter
    def _state(self, new_state: ThreadState):
        if self._thread_state == new_state:
            self._logger.warning(f"State is already is {self._thread_state.name}")
            return
        self._logger.core(f"Changing state: {self._thread_state.name} -> {new_state.name}")
        self._thread_state = new_state

    @property
    def input_queue(self) -> FixedTypedConcurrentDequeue[InternalQueuedItem]:
        return self._input_queue

    @property
    def output_queue(self) -> FixedTypedConcurrentDequeue[InternalQueuedItem]:
        return self._output_queue
    @property
    def stop_signal(self) -> threading.Event:
        return self._stop_signal
    @property
    def mutex(self) -> threading.Lock:
        return self._mutex

    @property
    def is_running(self) -> bool:
        return self._state in (ThreadState.RUNNING, ThreadState.FINALIZING, ThreadState.FINALIZED)

    @with_mutex("mutex")
    def finalize(self):
        "Only sets signal flag, changes state, clears inner queues"
        if self._state not in ThreadState.FINALIZING:
           self._logger.debug("Starting finalize")
           self._state = ThreadState.FINALIZING
           self._stop_signal.set() if not self._stop_signal.is_set() else self._logger.warning("Stop signal was set before finalize call")
        for q in (self._input_queue, self._output_queue):
            q.drop()
        self._state = ThreadState.FINALIZED
