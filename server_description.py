import json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Union, List, Dict, Self, Optional, Any

import numpy as np

_TOX_ID = "E7B2DD4DBF47295A58F372F5FA4A88CB655999D23ABE5415CF00E7400551A901A15477F334F2"
_TIME_FMT = "%d.%m.%y %H:%M:%S"
_AES256_KEY = "BF9514A1BBFA307092C4971CBDE621BEE381BB00EF1B8841356A6428F5288B58"


class __DataclassEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, OrderedDataclass):
            return obj.to_dict()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        return super().default(obj)


@dataclass
class OrderedDataclass:

    def to_dict(self):
        return dict()


@dataclass
class Param(OrderedDataclass):
    name: str
    fullname: str
    default_value: Union[str, int, np.dtype]
    description: str

    def to_dict(self):
        return {"name": self.name, "default_value": self.default_value, "description": self.description}


@dataclass
class EndpointPart(OrderedDataclass):
    description: str
    method: str
    params: List[Param]
    presets: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def to_dict(self):
        j = {"type": "endpoint", "description": self.description,
                "method": self.method, "params": [p.to_dict() for p in self.params]}
        if self.presets:
            j["presets"] = self.presets
        return j


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



_wav_params_descr: List[Param] = [Param("ch", "channels", 2, "Channels count"), Param("depth", "channel_bit_depth", 16, "Channel depth in bits count"),
                                  Param("freq", "samples_rate", 44100, "Samples Rate"), Param("dt", "data_type", "int16", "Type for low level operations with samples")]
_wav_duration_params_descr = [Param("t", "duration", 0, "Duration of stream in seconds, use 0 for unlimited stream")]
_wav_fsk_params_descr: List[Param] = [Param("fssc", "full_vs_symbol_samples_count", 196, "Samples count in seq of value+sync symbols"), Param("vssc", "value_symbol_samples_count", 68, "Samples count in seq of value symbol")]
_aes_params_descr: List[Param] = [Param("key", "key_str", _AES256_KEY, "256 bits key"), Param("iv", "iv_length", 12, "Initialization Vector (IV) length in bytes"), Param("tag", "tag", "notag", "GCM mode Authentication Tag")]
_presets = {"std44100_16n":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 44100, "value_symbol_samples_count": 64, "full_vs_symbol_samples_count": 180},     #245
            "std48000_16vl": {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 480, "full_vs_symbol_samples_count": 1200},   #40
            "std48000_16l":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 192, "full_vs_symbol_samples_count": 400},    #120
            "std48000_16n":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 108, "full_vs_symbol_samples_count": 240},    #200
            "std48000_16f":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 56, "full_vs_symbol_samples_count": 150},     #320
            "std48000_16vf": {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 32, "full_vs_symbol_samples_count": 96},      #500
            "std96000_16vl": {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 720, "full_vs_symbol_samples_count": 1600},   #60
            "std96000_16l":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 480, "full_vs_symbol_samples_count": 960},    #100
            "std96000_16n":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 384, "full_vs_symbol_samples_count": 640},    #150
            "std96000_16h":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 192, "full_vs_symbol_samples_count": 480},    #200
            "std96000_16f":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 128, "full_vs_symbol_samples_count": 384},    #250
            "std96000_16vf": {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 64, "full_vs_symbol_samples_count": 160},     #600
            }
_endpoints = {"wav": RoutePart("Uncompressed audio",
                               {
                                "random": RoutePart("Random outgoing data", {
                                                                            "stream": EndpointPart("Raw audio/wav stream", "GET", _wav_params_descr + _wav_duration_params_descr),
                                                                            "aes256": RoutePart("AES-256+GCM encoding", {
                                                                                                                        "stream": EndpointPart("AES-256+GCM encoded audio/wav stream", "GET", _wav_params_descr + _wav_duration_params_descr + _aes_params_descr)
                                                                                                                        }),
                                                                            "FSK2": RoutePart("FSK2 modulation", {
                                                                                                                 "stream": EndpointPart("FSK2 audio/wav stream", "GET", _wav_params_descr + _wav_duration_params_descr + _wav_fsk_params_descr, _presets),
                                                                                                                 }),
                                                                            }),
                                }),
              }
_main = Main("yue-ws-main", "online", datetime.now(), "JST", _TOX_ID, _endpoints)


def __get_params_from_request(args, params_descr: List[Param]) -> Optional[Dict[str, Any]]:
    return {pd.fullname: args.get(pd.name, default=pd.default_value, type=type(pd.default_value)) for pd in params_descr}


def get_wav_params(args) -> Optional[Dict[str, Any]]:
    return __get_params_from_request(args, _wav_params_descr + _wav_duration_params_descr)


def get_wav_fsk2_params(args) -> Optional[Dict[str, Any]]:
    if preset := _presets.get(args.get("preset")):
        p = preset.copy()
        p.update(__get_params_from_request(args, _wav_duration_params_descr))
        return p
    return __get_params_from_request(args, _wav_params_descr + _wav_fsk_params_descr)


def get_aes_params(args) -> Optional[Dict[str, Any]]:
    return __get_params_from_request(args, _aes_params_descr)


def get_system_info() -> str:
    return json.dumps(_main, cls=__DataclassEncoder, indent=4)
