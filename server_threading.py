import threading

from server_logging import EndpointLogger
from server_queue import FixedTypedConcurrentDequeue, InternalQueuedItem
from server_storage import with_mutex

class IOQueuedThread(threading.Thread):
    def __init__(self, logger: EndpointLogger, uname: str, in_queue_size: int, out_queue_size: int):
        super().__init__(daemon=True)
        self._logger = logger
        self._name = uname
        self._in_queue_size = in_queue_size
        self._out_queue_size = out_queue_size
        self._input_queue: FixedTypedConcurrentDequeue = None
        self._output_queue: FixedTypedConcurrentDequeue = None
        self._init_internal_dequeues()
        self._mutex = threading.Lock()
        self._stop_signal = threading.Event()

    @property
    def name(self) -> str:
        return self._name

    def _init_internal_dequeues(self):
        self._input_queue: FixedTypedConcurrentDequeue = FixedTypedConcurrentDequeue[InternalQueuedItem](self._logger, self._in_queue_size, f"{self._name}_input_queue")
        self._output_queue: FixedTypedConcurrentDequeue = FixedTypedConcurrentDequeue[InternalQueuedItem](self._logger, self._out_queue_size, f"{self._name}_output_queue")

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
        return self._running

    @with_mutex("mutex")
    def finalize(self, join: bool = False, recreate_queues: bool = True):
        if self.is_running and not self.stop_signal.is_set():
            self._running = False
            self.stop_signal.set()
            if recreate_queues:
                self.input_queue.recreate()
                self.output_queue.recreate()
            else:
                self.input_queue = None
                self.output_queue = None
        if join:
            self.join()

    @with_mutex("mutex")
    def renew(self, timeout: float = 30.0, reinit_dequeues: bool = False, reset_internal_flags: bool = True) -> bool:
        if self.is_alive() and self.stop_signal.is_set():
            self.join(timeout)
            if not self.is_alive():
                self._logger.system(f"Thread: {self.name} is finalized, memory allocated for internal structs is freed!")

                if reinit_dequeues:
                    self._init_internal_dequeues()
                if hasattr(self, '_started'):
                    self._started._flag = False
                if hasattr(self, '_tstate_lock'):
                    self._tstate_lock = None
                self.stop_signal.clear()
                self._logger.warning(f"Thread: {self.name} is renewed, internal structs resets and now it is ready for start() again! But this method depends from interpritater and NOT recomended!")
                return True
            else:
                return False

    @with_mutex("mutex")
    def stop_command(self, immediately: bool = True):
        self._logger.notify(f"Stop command received {"immediately" if immediately else ""}")
        cmd = ("stop", None)
        self._input_queue.put_top(cmd) if immediately else self._input_queue.put(cmd)