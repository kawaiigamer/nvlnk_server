import json
from dataclasses import dataclass, asdict
from typing import Tuple, List

from server_cryptography import AESCrypterCBC

_PRIVATE_STORAGE_FILE_PATH = "./private/server_private.bin"


@dataclass(frozen=True)
class MeshtasticNodePrivateData:
    short_name: str
    mac: str | None = None
    mac_name: str | None = None
    real_position: Tuple[float, float] | None = None


@dataclass(frozen=True)
class EndpointPrivateData:
    version: float
    release_type: str
    default_session_lifetime_seconds: int
    tox_id: str
    tox_profile_name: str
    tox_profile_password: str
    aes265_key: str
    access_key: str
    detetime_fmt: str
    log_fmt: str
    logger_name: str
    meshtastic_nodes: List[MeshtasticNodePrivateData] | None = None


def save_private_data(data: EndpointPrivateData, secret_key: str) -> None:
    json_str = json.dumps(asdict(data))
    plain_text_bytes = json_str.encode('utf-8')
    cipher = AESCrypterCBC(key_str=secret_key, iv_length=16)
    encrypted_bytes = cipher.encrypt(plain_text_bytes)
    with open(_PRIVATE_STORAGE_FILE_PATH, "wb") as f:
            f.write(encrypted_bytes)


def load_private_data(secret_key: str) -> EndpointPrivateData:
    cipher = AESCrypterCBC(key_str=secret_key, iv_length=16)
    with open(_PRIVATE_STORAGE_FILE_PATH, "rb") as f:
            json_data = json.loads(cipher.decrypt(f.read()))
            if json_data.get('meshtastic_nodes') is not None:
                json_data['meshtastic_nodes'] = [
                    MeshtasticNodePrivateData(**node) for node in json_data['meshtastic_nodes']
                ]
            return EndpointPrivateData(**json_data)


__EXAMPLE = EndpointPrivateData(version=0.031, release_type="DUBUG_ONLY", default_session_lifetime_seconds=10,
                                tox_id="E7B2DD4DBF47295A58F372F5FA4A88CB655999D23ABE5415CF00E7400551A901A15477F334F2",
                                tox_profile_name="nqwst_t.tox", tox_profile_password="7097152",
                                aes265_key="BF9514A1BBFA307092C4971CBDE621BEE381BB00EF1B8841356A6428F5288B58",
                                access_key="7E74516EFA4FD55DE3E7CD017DF7D364D2DF7B94122740476DFBFB5F10523D6F",
                                detetime_fmt="%d.%m.%y %H:%M:%S", log_fmt="[%(threadName)s] %(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
                                logger_name="NVLNK",
                                meshtastic_nodes=[MeshtasticNodePrivateData("NRTR", "A4:CB:8F:A2:18:05", "NRTR_1804", (60.032861, 30.345513))])
#save_private_data(__EXAMPLE, "898946929E5274DDE600CD7788B6C557377716197A59A6C5D9063A22C9E40741")
