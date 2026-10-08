import json
import pathlib
from dataclasses import dataclass, asdict, field
from datetime import timedelta
from typing import Tuple, Union, Dict, List
from frozendict import frozendict

from src.protocol7.cryptography import AES256CrypterCBC


_MODULE_CONSTS = frozendict(STORAGE_FILE_PATH=f"{pathlib.Path(__file__).resolve().parent.parent.parent}/private/server_private.bin", HMAC_KEY="何でもあってるから安全だ！")


@dataclass(frozen=True)
class InstanceThreadConfig:
    instance_name: str
    input_queue_max_size: int = 32
    output_queue_max_size: int = 512
    interval: Union[float, None] = 2.500


@dataclass
class MeshtasticInternalNodeData:
    short_name: str
    mac: str | None = None
    mac_address_name: str | None = None
    new_metrics_add_delta_sec: float = timedelta(seconds=30).total_seconds()
    new_node_add_delta_sec: float = timedelta(hours=36).total_seconds()
    real_position: Tuple[float, float] | None = None
    only_lora: bool = True
    instance_config: InstanceThreadConfig | None = None

    def __post_init__(self):
        if not self.instance_config:
            self.instance_config = InstanceThreadConfig(f"meshtastic_{self.short_name}")


@dataclass(frozen=True)
class ToxClientConfig:
    profile_file_name: str
    private_key: str
    bootstrap_ip: str
    bootstrap_port: int
    bootstrap_key: str
    instance_config: InstanceThreadConfig = InstanceThreadConfig("tox")
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
    version: EndpointVersion = EndpointVersion(0,0,0,0)
    release_type: str = "PRE_INIT"
    http_session_lifetime: int = 10
    aes256_key: str = ""
    http_access_key: str = ""
    timezone: str = "Asia/Tokyo"
    detetime_fmt: str = ""
    log_fmt: str = ""
    logger_name: str = ""
    logger_visualize_colour_scheme: bool = True
    tox_config: ToxClientConfig | None = None
    meshtastic_nodes: Dict[str, MeshtasticInternalNodeData] = field(default_factory=dict)


def save_private_data(data: EndpointPrivateConfig, secret_key: str) -> None:
    json_str = json.dumps(asdict(data))
    plain_text_bytes = json_str.encode('utf-8')
    cipher = AES256CrypterCBC(key=secret_key, hmac_key=_MODULE_CONSTS["HMAC_KEY"])
    encrypted_bytes = cipher.encrypt(plain_text_bytes)
    with open(_MODULE_CONSTS["STORAGE_FILE_PATH"], "wb") as f:
            f.write(encrypted_bytes)


def load_private_data(secret_key: str|None) -> EndpointPrivateConfig:
    if secret_key is None:
        return EndpointPrivateConfig()
    cipher = AES256CrypterCBC(key=secret_key, hmac_key=_MODULE_CONSTS["HMAC_KEY"])
    with open(_MODULE_CONSTS["STORAGE_FILE_PATH"], "rb") as f:
            json_data = json.loads(cipher.decrypt(f.read()))
            json_data["version"] = EndpointVersion(**json_data["version"])
            if json_data.get('meshtastic_nodes') is not None:
                node_names: List[str] = [str(mn) for mn in json_data.get('meshtastic_nodes').keys()]
                for node_name in node_names:
                    instance_config = InstanceThreadConfig(**json_data.get('meshtastic_nodes').get(node_name).pop("instance_config"))
                    json_data['meshtastic_nodes'][node_name] = MeshtasticInternalNodeData(instance_config=instance_config, **json_data.get('meshtastic_nodes').get(node_name))
            if json_data.get('tox_config') is not None:
                instance_config = InstanceThreadConfig(**json_data.get('tox_config').pop("instance_config"))
                json_data["tox_config"] = ToxClientConfig(instance_config=instance_config, **json_data.get('tox_config'))
    return EndpointPrivateConfig(**json_data)


if __name__ == "__main__":
    __EXAMPLE = EndpointPrivateConfig(version=EndpointVersion(0, 0, 32, 0), release_type="DUBUG_ONLY",
                                      http_session_lifetime=10,
                                      aes256_key="BF9514A1BBFA307092C4971CBDE621BEE381BB00EF1B8841356A6428F5288B58",
                                      http_access_key="7E74516EFA4FD55DE3E7CD017DF7D364D2DF7B94122740476DFBFB5F10523D6F",
                                      detetime_fmt="%d.%m.%y %H:%M:%S",
                                      log_fmt="[%(threadName)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(asctime)s | %(message)s",
                                      logger_name="NVLNK",

                                      tox_config=ToxClientConfig(
                                          profile_file_name="default",
                                          private_key="8a7f2c19e04b6d3f5a8c9e102f34a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2",
                                          bootstrap_ip="nodes.tox.chat", bootstrap_port=33445,
                                          bootstrap_key="3091C6BEB2A993F1C6300EE1B91392A7A446CE1A7C3D3CFE3A4BCEAA01C98725",
                                      ),

                                      meshtastic_nodes={node.short_name: node for node in [
                                          MeshtasticInternalNodeData(short_name="NRTR", mac="A4:CB:8F:A2:18:05",
                                                                     mac_address_name="NRTR_1804",
                                                                     real_position=(60.032861, 30.345513))]
                                                        })
    save_private_data(__EXAMPLE, "898946929E5274DDE600CD7788B6C557377716197A59A6C5D9063A22C9E40741")

