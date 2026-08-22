import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Union, List, Dict, Self, Optional, Any, Type, Tuple

import numpy as np

from server_private import load_private_data, EndpointPrivateData

__SECRET_KEY_256 = "898946929E5274DDE600CD7788B6C557377716197A59A6C5D9063A22C9E40741"
PRIVATE_DATA: EndpointPrivateData = load_private_data(__SECRET_KEY_256)


@dataclass
class OrderedDataclass:

    def to_dict(self):
        return dict()


class __DataclassEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, OrderedDataclass):
            return obj.to_dict()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.hex().upper()
        return super().default(obj)


@dataclass
class Param(OrderedDataclass):
    name: str
    fullname: str
    default_value: Union[str, int, np.dtype, bytes, float]
    description: str
    data_type: Type = None

    def __post_init__(self):
        self.data_type = type(self.default_value)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "fullname": self.fullname,
                "data_type": self.data_type.__name__, "default_value": self.default_value,
                "description": self.description}


@dataclass
class EndpointPart(OrderedDataclass):
    description: str
    method: str
    params: List[Param]
    post_params: List[Param] = field(default_factory=list)
    presets: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        j = {"type": "endpoint", "description": self.description,
                "method": self.method, "params": [p.to_dict() for p in self.params]}
        if self.post_params:
            j["post_params"] = [p.to_dict() for p in self.post_params]
        if self.presets:
            j["presets"] = self.presets
        return j


@dataclass
class RoutePart(OrderedDataclass):
    description: str
    parents: Dict[str, Union[Self, EndpointPart]]

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "route", "description": self.description,
                "parents": {k: v.to_dict() for k, v in self.parents.items()}}


@dataclass
class Main(OrderedDataclass):
    name: str
    status: str
    started_at: datetime
    timezone: str
    tox_id: str
    services: Dict[str, Union[RoutePart, EndpointPart]]

    @property
    def running_time(self) -> str:
        ts: int = int((datetime.now() - self.started_at).total_seconds())
        hours, remainder = divmod(ts, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    @property
    def started_time(self) -> str:
        return self.started_at.strftime(PRIVATE_DATA.detetime_fmt)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "status": self.status, "started_at": self.started_time, "timezone": self.timezone,
                "running_time": self.running_time, "tox_id": self.tox_id,
                "services": {k: v.to_dict() for k, v in self.services.items()}}

#  ------------------------------------- wav  params -------------------------------------
_wav_params_descr: List[Param] = [Param("ch", "channels", 2, "Channels count"), Param("depth", "channel_bit_depth", 16, "Channel depth in bits count"),
                                  Param("freq", "samples_rate", 44100, "Samples Rate"), Param("dt", "data_type", "int16", "Type for low level operations with samples"),
                                  #Param("lg", "logger", handler.logger, "Basing logger")
                                  ]
_wav_duration_params_descr = [Param("t", "duration", 0, "Duration of stream in seconds, use 0 for unlimited stream")]
_wav_nfsk_params_descr: List[Param] = [Param("fssc", "full_vs_symbol_samples_count", 196, "Samples count in seq of value+sync symbols"), Param("vssc", "value_symbol_samples_count", 68, "Samples count in seq of value symbol")]
_wav_nfsk_level_params_descr: List[Param] = [Param("lv", "fsk_level", 2, "Level of FSK(bits per one value symbol), ex: 2(1 bit), 4(2 bits), 8(3 bits), 16(4 bits), 32(5 bits), 64(6 bits), 128(7 bits), 256(8 bits)"),
                                             Param("sm", "smoothing", 1.0, "Smooth generated symbols by coff -><-")
                                             ]
_wav_dynamic_nfsk_params_descr: List[Param] = [Param("dfsk", "dynamic_fsk", "false", "Randomly changing level(N) for N-FSK(+symbols values) for every next frame in setted interval"),
                                               Param("dfsk_min", "dynamic_fsk_min", 4, "Min level for dynamic FSK"), Param("dfsk_max", "dynamic_fsk_max", 256, "Max level for dynamic FSK"),
                                               Param("dsm", "dynamic_smoothing", "false", "Randomly changing smoothing for every next frame in setted interval"),
                                               Param("dsm_min", "dynamic_smoothing_min", 1.0, "Min level for dynamic FSK"), Param("dsm_max", "dynamic_smoothing_max", 3.0, "Max level for dynamic FSK"),
                                               ]
_wav_nfsk_decrypt_errors_descr: List[Param] = [Param("errors", "errors_mode", "ignore", "'ignore' - ignores any error, 'break' - interrupts decrypt process, 'skip' - skipping error frame, continuing to next frame")]
_aes_params_descr: List[Param] = [Param("key", "key_str", PRIVATE_DATA.aes265_key, "256 bits key"), Param("mode", "mode", "CBC", "AES256 mode(GCM or CBC)"),
                                  Param("iv", "iv_length", 16, "Initialization Vector (IV) length in bytes"), Param("tag", "tag", "notag", "Authentication Tag(only for GCM mode)")
                                  ]
_aes_text_params_descr: List[Param] = [Param("text", "text", "", "Plain text for encryption")]
_wav_additional_params_descr: List[Param] = [Param("info_only", "info_only", "false", "Get json info instead of of stream")]
_post_wav_file_params_descr: List[Param] = [Param("file", "file", b"", "Wav file raw data")]
_post_aes_text_params_descr: List[Param] = [Param("text", "text", "", "Plain text for encryption")]
_fsk_presets: Dict[str, int] = {
                                    "std44100_16n":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 44100, "value_symbol_samples_count": 64, "full_vs_symbol_samples_count": 180},  #245
                                    "std48000_16vl": {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 480, "full_vs_symbol_samples_count": 1200},  #40
                                    "std48000_16l":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 192, "full_vs_symbol_samples_count": 400},  #120
                                    "std48000_16n":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 108, "full_vs_symbol_samples_count": 240},  #200
                                    "std48000_16f":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 56, "full_vs_symbol_samples_count": 150},  #320
                                    "std48000_16vf": {"channels": 2, "channel_bit_depth": 16, "samples_rate": 48000, "value_symbol_samples_count": 32, "full_vs_symbol_samples_count": 96},  #500
                                    "std48000_32vf": {"channels": 2, "channel_bit_depth": 32, "data_type": "int32", "samples_rate": 48000, "value_symbol_samples_count": 32, "full_vs_symbol_samples_count": 96},
                                    "std96000_16vl": {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 720, "full_vs_symbol_samples_count": 1600},  #60
                                    "std96000_16l":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 480, "full_vs_symbol_samples_count": 960},  #100
                                    "std96000_16n":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 384, "full_vs_symbol_samples_count": 640},  #150
                                    "std96000_16h":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 192, "full_vs_symbol_samples_count": 480},  #200
                                    "std96000_16f":  {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 128, "full_vs_symbol_samples_count": 384},  #250
                                    "std96000_16vf": {"channels": 2, "channel_bit_depth": 16, "samples_rate": 96000, "value_symbol_samples_count": 64, "full_vs_symbol_samples_count": 160},  #600
                                    "std96000_32vf": {"channels": 2, "channel_bit_depth": 32, "data_type": "int32", "samples_rate": 96000, "value_symbol_samples_count": 64, "full_vs_symbol_samples_count": 160},
                                }
#  ------------------------------------- wav  params -------------------------------------

#  ------------------------------------- meshtastic  params ------------------------------
_meshtastic_node_descr: List[Param] = [Param("ID", "short_name", "", "If multiple nodes are connected, you MUST specify a 4-character callsign for a specific node. If only one node is connected, no explicit indication is required.")]
_meshtastic_get_node_descr: List[Param] = [Param("count", "count", 250, "Number of requested nodes"), Param("save", "save", "true", "Save the result to internal storage")]
#  ------------------------------------- meshtastic  params ------------------------------

_endpoints: Dict[str, Union[RoutePart, EndpointPart]] = {
                                            #  ------------------------------------- wav -------------------------------------
                                            "wav": RoutePart("Uncompressed audio",  {
                                                                            "random": RoutePart("Streams using random data as source", {
                                                                            "stream": EndpointPart("Raw audio/wav stream", "GET", _wav_params_descr + _wav_duration_params_descr + _wav_additional_params_descr),
                                                                            "aes256": RoutePart("AES-256(GCM/CBC) encoding", {
                                                                                                                        "stream": EndpointPart("AES-256(GCM/CBC) encoded audio/wav stream", "GET", _wav_params_descr + _wav_duration_params_descr + _wav_additional_params_descr + _aes_params_descr)
                                                                                                                        }),
                                                                            "N-FSK": RoutePart("N-FSK(Frequency Shift Keying) modulation", {
                                                                                                                 "stream": EndpointPart("N-FSK audio/wav stream", "GET", _wav_params_descr + _wav_duration_params_descr + _wav_additional_params_descr + _wav_nfsk_params_descr + _wav_nfsk_level_params_descr + _wav_dynamic_nfsk_params_descr, presets=_fsk_presets),
                                                                                                                 }),
                                                                            "aes256_N-FSK": RoutePart("AES-256(GCM/CBC)+N-FSK(Frequency Shift Keying) modulation", {
                                                                                                                 "stream": EndpointPart("AES-256(GCM/CBC)+N-FSK audio/wav stream", "GET", _wav_params_descr + _wav_duration_params_descr + _wav_additional_params_descr + _wav_nfsk_params_descr + _wav_nfsk_level_params_descr + _wav_dynamic_nfsk_params_descr + _aes_params_descr),
                                                                                                                 }),
                                                                            },),
                                "text": RoutePart("Text to audio encrypt/decrypt utils", {
                                                                            "aes256_N-FSK": RoutePart("Text to/from audio/wav encoding/decoding via AES-256(GCM/CBC)+N-FSK", {
                                                                                                                        "crypter": EndpointPart("Text to audio/wav AES-256(GCM/CBC)+N-FSK crypter(plain text -> bytes -> AES-256 -> bytes -> bits -> wav header + frames[each frame constants any value symbols, each value symbol codes some bits count(1-8)])", "GET, POST", _wav_params_descr + _wav_nfsk_params_descr + _wav_nfsk_level_params_descr + _wav_dynamic_nfsk_params_descr  + _aes_params_descr + _aes_text_params_descr, presets=_fsk_presets, post_params=_post_aes_text_params_descr),
                                                                                                                        "crypter/form": EndpointPart("Form for plain text inputting", "GET", []),
                                                                                                                        "decrypter": EndpointPart("Audio/wav file to text AES-256(GCM/CBC)+N-FSK decrypter(wav header + frames[each frame constants any value symbols, each value symbol codes some bits count(1-8)] -> frames -> "
                                                                                                                                                  "bytes -> value symbols -> bits -> bytes -> AES-256 -> bytes -> plain text)\n"
                                                                                                                                                  "Fully supports dynamic N-FSK, FSK config(level, symbols values) updates for each frame! Automatically detects all wav parameters(sample rate, channels, channel data type, etc)", "GET, POST", _wav_nfsk_params_descr + _wav_nfsk_level_params_descr + _wav_dynamic_nfsk_params_descr + _wav_nfsk_decrypt_errors_descr + _aes_params_descr + _aes_text_params_descr , post_params=_post_wav_file_params_descr),
                                                                                                                        }),
                                                                            },),
                                #  ------------------------------------- wav -------------------------------------

                                #  ------------------------------------- meshtastic -------------------------------------
                                "meshtastic": RoutePart("Meshtastic introduction service", {
                                    "get_nodes": EndpointPart("Returns current node list json or error", "GET", _meshtastic_get_node_descr)})}
                                #  ------------------------------------- meshtastic -------------------------------------


                                )
                                }
_main = Main("yue-ws-main", "online", datetime.now(), "JST", PRIVATE_DATA.tox_id, _endpoints)


def __get_params_from_request(args, params_descr: List[Param]) -> Optional[Dict[str, Any]]:
    return {pd.fullname: args.get(pd.name, default=pd.default_value, type=type(pd.default_value)) for pd in params_descr}


def get_wav_params(args) -> Optional[Dict[str, Any]]:
    return __get_params_from_request(args, _wav_params_descr + _wav_duration_params_descr)


def get_wav_fsk_params(args) -> Optional[Dict[str, Any]]:
    if preset := _fsk_presets.get(args.get("preset")):
        return {**preset, **__get_params_from_request(args, _wav_duration_params_descr + _wav_additional_params_descr + _wav_nfsk_level_params_descr  + _wav_nfsk_decrypt_errors_descr + _wav_dynamic_nfsk_params_descr)}
    return __get_params_from_request(args, _wav_params_descr + _wav_additional_params_descr + _wav_duration_params_descr + _wav_nfsk_params_descr + _wav_nfsk_level_params_descr  + _wav_nfsk_decrypt_errors_descr + _wav_dynamic_nfsk_params_descr)


def get_aes_params(args) -> Optional[Dict[str, Any]]:
    return __get_params_from_request(args, _aes_params_descr + _aes_text_params_descr)


def get_system_info() -> str:
    return json.dumps(_main, cls=__DataclassEncoder, indent=4, ensure_ascii=False)


def get_private_data() -> EndpointPrivateData:
    return PRIVATE_DATA