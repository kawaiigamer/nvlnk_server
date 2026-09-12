import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar, Optional, Union, Dict
from collections import deque

from server_logging import EndpointLogger
from server_storage import with_mutex


@dataclass(frozen=True)
class InternalQueuedItem:
    content: Union[Dict, str]
    main_type: str | None = None
    sub_type: str | None = None
    uuid: str = str(uuid.uuid4())
    timestamp: datetime = datetime.now()

    def to_json(self) -> Dict:
        return {"datetime": self.timestamp.strftime("%d.%m.%y %H:%M:%S"), "content": self.content,
                "main_type": self.main_type, "sub_type": self.sub_type}


_T = TypeVar('T')


class LimitedTypedQueue(Generic[_T]):
    def __init__(self, logger: EndpointLogger, max_size: int, name: str) -> None:
        self._queue: deque[_T] = deque(maxlen=max_size)
        self._loger = logger
        self.__mutex = threading.Lock()
        self._name = name
        self._loger.info(f"Initialized {self._name} {self.__class__.__name__} with max length: {max_size}")

    @property
    def name(self) -> str:
        return self._name

    @with_mutex
    def put(self, item: _T) -> None:
        self._queue.append(item)

    @with_mutex
    def get(self) -> Optional[_T]:
        if not self._queue:
            self._loger.error("Attempting to get an element from an empty queue!")
            return None
        return self._queue.popleft()

    @with_mutex
    def is_empty(self) -> bool:
        return len(self._queue) == 0

    @with_mutex
    def __len__(self) -> int:
        return len(self._queue)

    @with_mutex
    def get_batch(self, max_count: int) -> list[_T]:
        items: list[_T] = []
        while self._queue and len(items) < max_count:
            items.append(self._queue.popleft())
        return items
