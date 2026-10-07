import threading
import uuid
from functools import wraps
from logging import Logger
from typing import Callable, Any
from frozendict import frozendict

from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, TypeVar, Optional, Union, Dict
from collections import deque


def with_mutex(mutex_name: str, wait: bool = True):
    def factory(f: Callable) -> Callable:
        @wraps(f)
        def mutex_function(self, *args, **kwargs):
            if mutex := getattr(self, mutex_name, None):
                if not wait and mutex.locked():
                    raise RuntimeError("Mutex is locked")
                with mutex:
                    return f(self, *args, **kwargs)
        return mutex_function
    return factory


_T1 = TypeVar('T1')
_T2 = TypeVar('T2')


class BiFrozenDict[_T1, _T2]:
    def __init__(self, d: Dict[_T1, _T2]):
        self.key_to_val = frozendict(d)
        self.val_to_key = frozendict({v: k for k, v in d.items()})

    def get(self, key): return self.key_to_val.get(key)
    def v_get(self, val): return self.val_to_key.get(val)
    def items(self): return self.key_to_val.items()
    def v_items(self): return self.val_to_key.items()
    def keys(self): return self.key_to_val.keys()
    def v_keys(self): return self.val_to_key.keys()
    def values(self): return self.key_to_val.values()
    def v_values(self): return self.val_to_key.values()


@dataclass(frozen=True)
class InternalQueuedItem:
    content: Union[Dict, str]
    main_type: str | None = None
    sub_type: str | None = None
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self, logger: Any) -> Dict:
        return {"datetime": logger.strftime(self.timestamp), "content": self.content,
                "main_type": self.main_type, "sub_type": self.sub_type}


_TF = TypeVar('TF')


class FixedTypedConcurrentDequeue(Generic[_TF]):
    def __init__(self, logger: Logger, max_size: int, name: str) -> None:
        self._loger = logger
        self._name = name
        self._deque: deque[_TF] = self._create_internal_deque(max_size)
        self._mutex = threading.Lock()

    def _create_internal_deque(self, max_size: int) -> deque[_TF]:
        self._loger.info(f"Initialing new {self.name} {self.__class__.__name__} with max size: {max_size}")
        return deque(maxlen=max_size)

    @property
    def name(self) -> str:
        return self._name
    @property
    def mutex(self) -> threading.Lock:
        return self._mutex

    @with_mutex("mutex")
    def put_top(self, item: _TF) -> None:
        self._deque.appendleft(item)

    @with_mutex("mutex")
    def put(self, item: _TF) -> None:
        self._deque.append(item)

    @with_mutex("mutex")
    def get(self) -> Optional[_TF]:
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
    def get_batch(self, max_count: int) -> list[_TF]:
        items: list[_TF] = []
        while self._deque and len(items) < max_count:
            items.append(self._deque.popleft())
        return items

    @with_mutex("mutex")
    def drop(self):
        if len(self._deque) > 0:
            self._loger.notify(f"Dropping {len(self._deque)} items from queue: {self.name}")
            self._deque = self._create_internal_deque(self._deque.maxlen)

