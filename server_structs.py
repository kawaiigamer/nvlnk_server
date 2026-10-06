from typing import TypeVar, Dict

from frozendict import frozendict

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
