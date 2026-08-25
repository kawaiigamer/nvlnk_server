import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Tuple

from meshtastic.serial_interface import SerialInterface
from geographiclib.geodesic import Geodesic

from server_logging import EndpointLogger


class MeshtasticWireException(BaseException):
    pass


def mesh_json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


@dataclass(frozen=True, eq=False)
class MeshtasticKnownNode:
    short_name: str
    full_name: str
    device_name: str
    role: str
    id: str
    number: int
    public_key: str
    hopes: int
    uptime_seconds: int | None = None
    last_online: datetime | None = None
    messagable: bool | None = None
    mac_address: str | None = None
    snr: float | None = None
    location: Tuple[float, float] | None = None
    altitude_meters: int | None = None
    favorite: bool = False
    channelUtilization_airUtilTx_provides: bool = False
    # --- Generated
    _distance_km: int | None = None
    _additional_data: str | None = None
    _internal_uuid: str = field(default_factory=lambda: str(uuid.uuid4()), init=False, repr=False)

    def __eq__(self, other):
        if not isinstance(other, MeshtasticKnownNode):
            return NotImplemented
        return (self.short_name == other.short_name and
                self.number == other.number and
                self.id == other.id)

    def __hash__(self):
        return hash((self.short_name, self.number, self.id))

    def to_json_str(self) -> str:
        return json.dumps(asdict(self), default=mesh_json_serial, ensure_ascii=False, indent=4)

class MeshtasticWireHandle:
    _ROLES = {
        # ----
        "CLIENT_BASE": True,
        "CLIENT": True,
        "CLIENT_MUTE": True,
        "CLIENT_HIDDEN": True,
        # ----
        "ROUTER": True,
        "ROUTER_LATE": True,
        "REPEATER": True,
        # ----
        "TRACKER": True,
        "SENSOR": True,
        # ----
        "TAK": True,
        "TAK_TRACKER": True,
        "LOST_AND_FOUND": True,
        # ----
        "UNKNOWN_ROLE": False,
    }

    def __init__(self, logger: EndpointLogger, name: str = None, real_position: Tuple[float, float] = None, mac_address: str = None):
        self.logger = logger
        self.usb_port_lock = threading.Lock()
        self.name = name
        self.real_position = real_position
        self.mac_address = mac_address

    @staticmethod
    def __bytes_to_mac_string(mac_bytes: Optional[bytes]) -> Optional[str]:
        if not mac_bytes or not isinstance(mac_bytes, bytes):
            return None
        return ":".join(f"{b:02X}" for b in mac_bytes)

    @staticmethod
    def nodes_to_json_str(nodes: List[MeshtasticKnownNode]) -> str:
        return json.dumps([asdict(node) for node in nodes], default=mesh_json_serial, ensure_ascii=False, indent=4)

    @staticmethod
    def __calculate_geodistanse_in_km(point_1: Tuple[float, float], point_2: Tuple[float, float]) -> float:
        return round(Geodesic.WGS84.Inverse(point_1[0], point_1[1], point_2[0], point_2[1])["s12"]/1000, 3)

    def get_all_known_nodes_via_usb_sync(self, dev_path: str = None, sync_tryes_count: int = 10, sync_try_sleep_sec: float = 1.0) -> List[MeshtasticKnownNode]:
        with self.usb_port_lock:
            return self.get_all_known_nodes_via_usb(dev_path, sync_tryes_count, sync_try_sleep_sec)

    def get_all_known_nodes_via_usb(self, dev_path: str = None, sync_tryes_count: int = 10, sync_try_sleep_sec: float = 1.0) -> List[MeshtasticKnownNode]:
        self.logger.debug(f"Trying connection to by wire - {dev_path if dev_path else "auto finding"}")
        try:
            interface = SerialInterface(devPath=dev_path)

            for i in range(sync_tryes_count):
                if not interface.nodes:
                    self.logger.info(f"[{i+1}/{sync_tryes_count}]Syncing with node...")
                    time.sleep(sync_try_sleep_sec)
                else:
                    break
            if not interface.nodes:
                self.logger.critical("The node database is empty or has not yet loaded! Aborting!")
                raise MeshtasticWireException

            interface.close()

            known_nodes_list: List[MeshtasticKnownNode] = []

            for node_id, raw_node in interface.nodes.items():
                user_data = raw_node.get("user", {})
                position_data = raw_node.get("position", {})

                role = user_data.get("role")
                if not self._ROLES.get(role, self._ROLES["UNKNOWN_ROLE"]):
                    continue

                # Extracting MAC-address
                raw_mac = user_data.get("macaddr")
                formatted_mac = self.__bytes_to_mac_string(raw_mac)

                # Datetime parsing
                last_heard_timestamp = raw_node.get("lastHeard")
                last_online_dt = (
                    datetime.fromtimestamp(last_heard_timestamp)
                    if last_heard_timestamp else None
                )

                location=(0,0)
                ch_a_aut_provides = False
                uptime_seconds=altitude_meters=None
                if position_data:
                    altitude_meters = position_data.get("altitude", -1)
                    location = (position_data.get("latitude"), position_data.get("longitude"))
                if dev_metrics := raw_node.get("deviceMetrics"):
                    uptime_seconds = dev_metrics.get("uptimeSeconds", -1)
                    ch_a_aut_provides = dev_metrics.get("channelUtilization") and dev_metrics.get("airUtilTx")

                is_valid_pos = self.real_position and all(c is not None for c in self.real_position)
                is_valid_loc = location and location != (0, 0) and all(c is not None for c in location)

                known_node = MeshtasticKnownNode(
                    short_name=user_data.get("shortName", "????"),
                    full_name=user_data.get("longName", "Unknown Node"),
                    device_name=user_data.get("hwModel", "UNKNOWN_HW"),
                    role=role,
                    id=node_id,
                    number=raw_node.get("num", -1),
                    public_key=user_data.get("publicKey", ""),
                    hopes=raw_node.get("hopsAway", -1),
                    uptime_seconds=uptime_seconds,
                    last_online=last_online_dt,
                    messagable=user_data.get("isUnmessagable", False),
                    snr=raw_node.get("snr", None),
                    location=location,
                    altitude_meters=altitude_meters,
                    _distance_km= self.__calculate_geodistanse_in_km(self.real_position, location) if is_valid_pos and is_valid_loc else None,
                    mac_address=formatted_mac,
                    channelUtilization_airUtilTx_provides=ch_a_aut_provides,
                    favorite=user_data.get("isFavorite", False)
                    # additional_data=f"Battery: {position_data.get('batteryLevel', 'N/A')}%",
                )
                known_nodes_list.append(known_node)

        except MeshtasticWireException as mwe:
            self.logger.exception(f"MeshtasticWireException: {mwe}")
            raise
        except Exception as e:
            self.logger.exception(f"Exception: {e}")
            raise
        return known_nodes_list

    def send_message(self, text: str, channel: int = 0, destinationId: int = -1, dev_path = None) -> None:
        self.logger.debug(f"Trying connection to by wire - {dev_path if dev_path else "auto finding"}")
        connected = False
        try:
            interface = SerialInterface(devPath=dev_path)
            connected = True
            self.logger.debug(f"Trying to send message Text: {text} Channel: {channel}, destinationId: {destinationId}")
            if destinationId != -1:
                interface.sendText(text, destinationId=destinationId)
            else:
                interface.sendText(text, channelIndex=channel)
        except MeshtasticWireException as mwe:
            self.logger.exception(f"MeshtasticWireException: {mwe}")
            raise
        else:
            self.logger.info(f"Message: {text} sent!")
        finally:
            if connected:
                interface.close()


def meshtastic_get_nodes(logger: EndpointLogger, mac: Optional[str] = None, short_name: Optional[str] = None,
                         mac_name: Optional[str] = None, real_position: Optional[Tuple[float, float]] = None,
                         count:int = 250) -> Optional[List[MeshtasticKnownNode]]:
    handle = MeshtasticWireHandle(name=short_name, real_position=real_position, mac_address=mac, logger=logger)
    nodes: List[MeshtasticKnownNode] = handle.get_all_known_nodes_via_usb()
    return nodes


def meshtastic_json_format_dumped_nodes(nodes: List[MeshtasticKnownNode]) -> str:
    return f'[{",\n".join([node.to_json_str() for node in nodes])}]'


def meshtastic_save_dumped_nodes(nodes: List[MeshtasticKnownNode]):
    os.makedirs("./meshtastic_data", exist_ok=True)
    with open(f"./meshtastic_data/known_nodes_dump_{datetime.now().strftime("%d.%m.%y_%H-%M-%S")}.json", "w+") as f:
        f.write(meshtastic_json_format_dumped_nodes(nodes))


def meshtastic_send_message(logger: EndpointLogger, text: str, channel: int = 0, destinationId: int = -1, short_name: str = None):
    handle = MeshtasticWireHandle(logger=logger)
    handle.send_message(text, channel, destinationId)



if __name__ == "__main__":
    NRTR_MAC = "A4:CB:8F:A2:18:05"
    NRTR_NAME = "NRTR"
    NRTR_MAC_NAME = "NRTR_1804"
    NRTR_POSITION = (60.032861, 30.345513)

#    handle = MeshtasticWireHandle(real_position=NRTR_POSITION)


