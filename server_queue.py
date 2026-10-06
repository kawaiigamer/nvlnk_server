import threading
import uuid
from dataclasses import dataclass, field
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
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self, logger: EndpointLogger) -> Dict:
        return {"datetime": logger.strftime(self.timestamp), "content": self.content,
                "main_type": self.main_type, "sub_type": self.sub_type}


_T = TypeVar('T')


class FixedTypedConcurrentDequeue(Generic[_T]):
    def __init__(self, logger: EndpointLogger, max_size: int, name: str) -> None:
        self._loger = logger
        self._name = name
        self._deque: deque[_T] = self._create_internal_deque(max_size)
        self._mutex = threading.Lock()

    def _create_internal_deque(self, max_size: int) -> deque[_T]:
        self._loger.info(f"Initialing new {self.name} {self.__class__.__name__} with max size: {max_size}")
        return deque(maxlen=max_size)

    @property
    def name(self) -> str:
        return self._name
    @property
    def mutex(self) -> threading.Lock:
        return self._mutex

    @with_mutex("mutex")
    def put_top(self, item: _T) -> None:
        self._deque.appendleft(item)

    @with_mutex("mutex")
    def put(self, item: _T) -> None:
        self._deque.append(item)

    @with_mutex("mutex")
    def get(self) -> Optional[_T]:
        if not self._deque:
            self._loger.error("Attempting to get an element from an empty queue!")
            return None
        return self._deque.popleft()

    @with_mutex("mutex")
    def is_empty(self) -> bool:
        return len(self._deque) == 0

    @with_mutex("mutex")
    def __len__(self) -> int:
        return len(self._deque)

    @with_mutex("mutex")
    def get_batch(self, max_count: int) -> list[_T]:
        items: list[_T] = []
        while self._deque and len(items) < max_count:
            items.append(self._deque.popleft())
        return items

    @with_mutex("mutex")
    def drop(self):
        if len(self._deque) > 0:
            self._loger.notify(f"Dropping {len(self._deque)} items from queue: {self.name}")
            self._deque = self._create_internal_deque(self._deque.maxlen)
