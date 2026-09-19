import json
from dataclasses import dataclass, asdict
from typing import Tuple, Union, Dict

from server_cryptography import AESCrypterCBC

_PRIVATE_STORAGE_FILE_PATH = "./private/server_private.bin"


@dataclass(frozen=True)
class MeshtasticInternalNodeData:
    short_name: str
    mac: str | None = None
    mac_address: str | None = None
    real_position: Tuple[float, float] | None = None
    input_queue_max_size: int = 42
    output_queue_max_size: int = 512
    interval: Union[float, None] = 2.500
    accept_invites: bool = True


@dataclass(frozen=True)
class ToxClientConfig:
    profile_name: str
    private_key: str
    bootstrap_ip: str
    bootstrap_port: int
    bootstrap_key: str
    input_queue_max_size: int = 32
    output_queue_max_size: int = 320
    interval: Union[float, None] = 1.000
    accept_invites: bool = True


@dataclass(frozen=True)
class EndpointVersion:
    major: int
    minor: int
    release: int
    debug: int

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.release}.{self.debug}"


@dataclass(frozen=True)
class EndpointPrivateConfig:
    version: EndpointVersion
    release_type: str
    http_session_lifetime: int
    aes265_key: str
    access_key: str
    detetime_fmt: str
    log_fmt: str
    logger_name: str
    tox_config: ToxClientConfig | None = None
    meshtastic_nodes: Dict[str, MeshtasticInternalNodeData] | None = None


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
                json_data['meshtastic_nodes'] = {val["short_name"]: MeshtasticInternalNodeData(**val) for val in json_data.get('meshtastic_nodes').values()}
            if json_data.get('tox_config') is not None:
                json_data["tox_config"] = ToxClientConfig(**json_data.get('tox_config'))
            json_data["version"] = EndpointVersion(**json_data["version"])
    return EndpointPrivateConfig(**json_data)


__EXAMPLE = EndpointPrivateConfig(version=EndpointVersion(0,0,31,1), release_type="DUBUG_ONLY", http_session_lifetime=10,
                                tox_config=ToxClientConfig(
                                profile_name="default",
                                private_key="8a7f2c19e04b6d3f5a8c9e102f34a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2",
                                bootstrap_ip="nodes.tox.chat", bootstrap_port=33445,
                                bootstrap_key="3091C6BEB2A993F1C6300EE1B91392A7A446CE1A7C3D3CFE3A4BCEAA01C98725",
                                input_queue_max_size=32, output_queue_max_size=320),
                                  aes265_key="BF9514A1BBFA307092C4971CBDE621BEE381BB00EF1B8841356A6428F5288B58",
                                  access_key="7E74516EFA4FD55DE3E7CD017DF7D364D2DF7B94122740476DFBFB5F10523D6F",
                                  detetime_fmt="%d.%m.%y %H:%M:%S", log_fmt="[%(threadName)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(asctime)s | %(message)s",
                                  logger_name="NVLNK",
                                  meshtastic_nodes={node.short_name: node for node in [MeshtasticInternalNodeData("NRTR", "A4:CB:8F:A2:18:05", "NRTR_1804", (60.032861, 30.345513))]})

if __name__ == "__main__":
    save_private_data(__EXAMPLE, "898946929E5274DDE600CD7788B6C557377716197A59A6C5D9063A22C9E40741")
