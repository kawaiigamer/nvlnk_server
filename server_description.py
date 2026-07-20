import dataclasses
from datetime import datetime
import json
from dataclasses import is_dataclass, asdict, dataclass, field
from typing import Union, List, Dict, Self, Tuple, Optional, Any

_TOX_ID = "E7B2DD4DBF47295A58F372F5FA4A88CB655999D23ABE5415CF00E7400551A901A15477F334F2"
_TIME_FMT = "%d.%m.%y %H:%M:%S"
_AES256_KEY = "BF9514A1BBFA307092C4971CBDE621BEE381BB00EF1B8841356A6428F5288B58"

class __DataclassEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, OrderedDataclass):
            return obj.to_dict()
        return super().default(obj)


@dataclass
class OrderedDataclass:

    def to_dict(self):
        return dict()


@dataclass
class Param(OrderedDataclass):
    name: str
    fullname: str
    default_value: Union[str, int]
    description: str

    def to_dict(self):
        return {"name": self.name, "default_value": self.default_value, "description": self.description}


@dataclass
class EndpointPart(OrderedDataclass):
    description: str
    method: str
    params: List[Param]

    def to_dict(self):
        return {"type": "endpoint", "description": self.description,
                "method": self.method, "params": [p.to_dict() for p in self.params]}


@dataclass
class RoutePart(OrderedDataclass):
    description: str
    parents: Dict[str, Union[Self, EndpointPart]]

    def to_dict(self):
        return {"type": "route", "description": self.description,
                "parents": {k: v.to_dict() for k, v in self.parents.items()}}


@dataclass
class Main(OrderedDataclass):
    name: str
    status: str
    started_at: datetime
    timezone: str
    tox_id: str
    services: Dict[str, RoutePart]
    @property
    def running_time(self) -> str:
        ts: int = int((datetime.now() - self.started_at).total_seconds())
        hours, remainder = divmod(ts, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    @property
    def started_time(self) -> str:
        return self.started_at.strftime(_TIME_FMT)

    def to_dict(self):
        return {"name": self.name, "status": self.status, "started_at": self.started_time, "timezone": self.timezone,
                "running_time": self.running_time, "tox_id": self.tox_id,
                "services": {k: v.to_dict() for k, v in self.services.items()}}



_wav_params_descr: List[Param] = [Param("ch", "channels", 2, "Channels count"), Param("depth", "channel_bit_depth", 16, "Channel depth in bits count"), Param("freq", "samples_rate", 44100, "Samples Rate")]
_aes_params_descr: List[Param] = [Param("key", "key_str", _AES256_KEY, "256 bits key"), Param("iv", "iv_length", 12, "Initialization Vector (IV) length in bytes"), Param("tag", "tag", "notag", "GCM mode Authentication Tag")]
_endpoints = {"wav": RoutePart("Uncompressed audio",
                               {
                                "random": RoutePart("Random outgoing data", {
                                                                            "stream": EndpointPart("Infinite raw audio/wav stream", "GET", _wav_params_descr),
                                                                            "aes256": RoutePart("AES-256+GCM encoding data over audio/wav stream", {
                                                                                                                                                   "stream": EndpointPart("Infinite AES-256+GCM encoded audio/wav stream", "GET", _wav_params_descr + _aes_params_descr)
                                                                                                                                                   }),

                                                                            }),
                                }),
              }

_main = Main("yue-ws-main", "online", datetime.now(), "JST", _TOX_ID, _endpoints)


def __get_params_from_request(request, params_descr: List[Param]) -> Optional[Dict[str, Any]]:
    return {pd.fullname: request.args.get(pd.name, default=pd.default_value, type=type(pd.default_value)) for pd in params_descr}


def get_wav_params(request) -> Optional[Dict[str, Any]]:
    return __get_params_from_request(request, _wav_params_descr)


def get_aes_params(request) -> Optional[Dict[str, Any]]:
    return __get_params_from_request(request, _aes_params_descr)


def get_system_info() -> str:
    return json.dumps(_main, cls=__DataclassEncoder, indent=4)
