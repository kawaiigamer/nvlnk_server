import json
from dataclasses import dataclass, asdict
from typing import Tuple, List, Union

from server_cryptography import AESCrypterCBC

_PRIVATE_STORAGE_FILE_PATH = "./private/server_private.bin"


@dataclass(frozen=True)
class MeshtasticInternalNodeData:
    short_name: str
    mac: str | None = None
    mac_name: str | None = None
    real_position: Tuple[float, float] | None = None
    queue_max_size: int = 512


@dataclass(frozen=True)
class ToxClientConfig:
    profile_name: str
    private_key: str
    queue_max_size: int
    interval: Union[float, None] = 1.000


@dataclass(frozen=True)
class EndpointPrivateConfig:
    version: float
    release_type: str
    default_session_lifetime_seconds: int
    aes265_key: str
    access_key: str
    detetime_fmt: str
    log_fmt: str
    logger_name: str
    default_queue_length: int
    tox_config: ToxClientConfig | None = None
    meshtastic_nodes: List[MeshtasticInternalNodeData] | None = None


def save_private_data(data: EndpointPrivateConfig, secret_key: str) -> None:
    json_str = json.dumps(asdict(data))
    plain_text_bytes = json_str.encode('utf-8')
    cipher = AESCrypterCBC(key_str=secret_key, iv_length=16)
    encrypted_bytes = cipher.encrypt(plain_text_bytes)
    with open(_PRIVATE_STORAGE_FILE_PATH, "wb") as f:
            f.write(encrypted_bytes)


def load_private_data(secret_key: str) -> EndpointPrivateConfig:
    cipher = AESCrypterCBC(key_str=secret_key, iv_length=16)
    with open(_PRIVATE_STORAGE_FILE_PATH, "rb") as f:
            json_data = json.loads(cipher.decrypt(f.read()))
            if json_data.get('meshtastic_nodes') is not None:
                json_data['meshtastic_nodes'] = [
                    MeshtasticInternalNodeData(**node) for node in json_data['meshtastic_nodes']
                ]
            if json_data.get('tox_config') is not None:
                json_data["tox_config"] = ToxClientConfig(**json_data.get('tox_config'))
            return EndpointPrivateConfig(**json_data)


__EXAMPLE = EndpointPrivateConfig(version=0.031, release_type="DUBUG_ONLY", default_session_lifetime_seconds=10, default_queue_length=512,
                               tox_config=ToxClientConfig(
                                profile_name="default", private_key="8a7f2c19e04b6d3f5a8c9e102f34a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2",
                                queue_max_size=320),
                                  aes265_key="BF9514A1BBFA307092C4971CBDE621BEE381BB00EF1B8841356A6428F5288B58",
                                  access_key="7E74516EFA4FD55DE3E7CD017DF7D364D2DF7B94122740476DFBFB5F10523D6F",
                                  detetime_fmt="%d.%m.%y %H:%M:%S", log_fmt="[%(threadName)s] [%(levelname)s] %(asctime)s | %(message)s",
                                  logger_name="NVLNK",
                                  meshtastic_nodes=[MeshtasticInternalNodeData("NRTR", "A4:CB:8F:A2:18:05", "NRTR_1804", (60.032861, 30.345513))])

if __name__ == "__main__":
    save_private_data(__EXAMPLE, "898946929E5274DDE600CD7788B6C557377716197A59A6C5D9063A22C9E40741")
