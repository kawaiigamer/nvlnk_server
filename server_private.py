import json
from dataclasses import dataclass, asdict
from typing import Tuple, List

from server_cryptography import AESCrypterCBC

__PRIVATE_STORAGE__PATH = "server_private.bin"


@dataclass(frozen=True)
class MeshtasticNodePrivateData:
    short_name: str
    mac: str | None = None
    mac_name: str | None = None
    real_position: Tuple[float, float] | None = None


@dataclass(frozen=True)
class EndpointPrivateData:
    tox_id: str
    aes265_key: str
    meshtastic_nodes: List[MeshtasticNodePrivateData] | None = None


def save_private_data(data: EndpointPrivateData, secret_key: str) -> None:
    json_str = json.dumps(asdict(data))
    plain_text_bytes = json_str.encode('utf-8')
    cipher = AESCrypterCBC(key_str=secret_key, iv_length=16)
    encrypted_bytes = cipher.encrypt(plain_text_bytes)
    with open(__PRIVATE_STORAGE__PATH, "wb") as f:
            f.write(encrypted_bytes)


def load_private_data(secret_key: str) -> EndpointPrivateData:
    cipher = AESCrypterCBC(key_str=secret_key, iv_length=16)
    with open(__PRIVATE_STORAGE__PATH, "rb") as f:
            json_data = json.loads(cipher.decrypt(f.read()))
            if json_data.get('meshtastic_nodes') is not None:
                json_data['meshtastic_nodes'] = [
                    MeshtasticNodePrivateData(**node) for node in json_data['meshtastic_nodes']
                ]
            return EndpointPrivateData(**json_data)


__EXAMPLE = EndpointPrivateData(tox_id="E7B2DD4DBF47295A58F372F5FA4A88CB655999D23ABE5415CF00E7400551A901A15477F334F2",
                                aes265_key="BF9514A1BBFA307092C4971CBDE621BEE381BB00EF1B8841356A6428F5288B58",
                                meshtastic_nodes=[MeshtasticNodePrivateData("NRTR", "A4:CB:8F:A2:18:05", "NRTR_1804", (60.032861, 30.345513))])