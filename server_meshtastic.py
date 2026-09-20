import json
import os
import threading
import time

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Tuple

from datalite.fetch import fetch_equals
from frozendict import frozendict
from meshtastic.serial_interface import SerialInterface
from geographiclib.geodesic import Geodesic
from datalite import datalite
from pubsub import pub

from server_logging import EndpointLogger
from server_private import MeshtasticInternalNodeData
from server_queue import InternalQueuedItem

import serial.tools.list_ports
import meshtastic.serial_interface

from server_storage import with_mutex
from server_threading import IOQueuedThread

_MODULE_CONSTS = frozendict(RUNTIME_DIR="meshtastic",
                            ROLES_ALLOWED = frozendict({
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
                            })
                            )


class MeshtasticWireException(BaseException):
    pass


def mesh_json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


@datalite(db_path=f"{_MODULE_CONSTS["RUNTIME_DIR"]}/nodes.db")
@dataclass(eq=False)
class MeshtasticKnownNode:
    short_name: str
    full_name: str
    device_name: str
    role: str
    id: str
    number: int
    public_key: str
    hopes: int
    last_online: str
    uptime_seconds: int = None
    messagable: bool = None
    mac_address: str = None
    snr: float = None
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_meters: int = -1
    favorite: bool = False
    channelUtilization_airUtilTx_provides: bool = False
    # --- Generated
    _distance_km: int = None
    _additional_data: str = None
    #_internal_uuid: str = field(default_factory=lambda: str(uuid.uuid4()), init=False, repr=False)

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


class MeshtasticWireHandleThread(IOQueuedThread):

    _PORT_DESCRIPTION = "USB JTAG/serial debug unit"
    _PORT_VID = 12346

    def __init__(self, logger: EndpointLogger, config: MeshtasticInternalNodeData):
        super().__init__(logger, config.instance_config)
        self._usb_port_mutex = threading.Lock()
        self._node_config = config
        self._interface = None
        pub.subscribe(self.on_receive_message, "meshtastic.receive")

    @property
    def usb_port_mutex(self) -> threading.Lock:
        return self._usb_port_mutex

    def save_dumped_nodes(self, nodes: List[MeshtasticKnownNode]):
        os.makedirs(_MODULE_CONSTS["RUNTIME_DIR"], exist_ok=True)
        with open(f"{_MODULE_CONSTS["RUNTIME_DIR"]}/known_nodes_dump_{datetime.now().strftime(self._logger.detetime_fmt)}.json",
                  "w+") as f:
            f.write(MeshtasticWireHandleThread._json_format_dumped_nodes(nodes))

    @staticmethod
    def _bytes_to_mac_string(mac_bytes: Optional[bytes]) -> Optional[str]:
        if not mac_bytes or not isinstance(mac_bytes, bytes):
            return None
        return ":".join(f"{b:02X}" for b in mac_bytes)

    @staticmethod
    def _json_format_dumped_nodes(nodes: List[MeshtasticKnownNode]) -> str:
        return f'[{",\n".join([node.to_json_str() for node in nodes])}]'

    @staticmethod
    def _nodes_to_json_str(nodes: List[MeshtasticKnownNode]) -> str:
        return json.dumps([asdict(node) for node in nodes], default=mesh_json_serial, ensure_ascii=False, indent=4)

    @staticmethod
    def _calculate_geodistanse_in_km(point_1: Tuple[float, float], point_2: Tuple[float, float]) -> float:
        return round(Geodesic.WGS84.Inverse(point_1[0], point_1[1], point_2[0], point_2[1])["s12"]/1000, 3)

    @with_mutex("usb_port_mutex")
    def _get_usb_interface(self) -> Optional[SerialInterface]:
        ports = serial.tools.list_ports.comports()
        self._logger.note(f"Founded {len(ports)} serial ports")
        usb_ports = []
        for port in ports:
            if port.description.startswith(self._PORT_DESCRIPTION) and port.vid == self._PORT_VID:
                usb_ports.append(port)
        self._logger.note(f"Founded {len(usb_ports)} devices: {[up.device for up in usb_ports]} with expected description and vid")
        for usb_port in usb_ports:
            interface = meshtastic.serial_interface.SerialInterface(
                devPath=usb_port.device,
                connectNow=True
            )
            my_node = interface.getMyNodeInfo()
            current_short_name = my_node.get('user', {}).get('shortName')
            if current_short_name == self._node_config.short_name:
                self._logger.debug(f"Interface {self._node_config.short_name} found")
                return interface
        if usb_ports:
            self._logger.critical(f"Interface {self._node_config.short_name} not found, using first another interface")
            return meshtastic.serial_interface.SerialInterface(
                devPath=usb_ports[0].device,
                connectNow=True
            )
        raise NameError("No nodes connected via USB were found")

    @with_mutex("usb_port_mutex")
    def send_message(self, text: str, channel: int = 0, destinationId: int = -1) -> None:
        self._logger.debug(f"Trying connection to by wire - {self._node_config.short_name if self._node_config.short_name else "auto finding"}")
        try:
            self._logger.debug(f"Trying to send message Text: {text} Channel: {channel}, destinationId: {destinationId}")
            if destinationId != -1:
                self._interface.sendText(text, destinationId=destinationId)
            else:
                self._interface.sendText(text, channelIndex=channel)
        except MeshtasticWireException as mwe:
            self._logger.exception(f"MeshtasticWireException: {mwe}")
            raise
        else:
            self._logger.info(f"Message: {text} sent!")

    @with_mutex("mutex")
    def _handle_command(self, cmd_type: str, data: Optional[Tuple[str, str]]):
         match cmd_type:
            case "send_msg":
                message_text, message_channel, destinationId = data
                self.send_message(message_text, message_channel, destinationId)
            case "stop":
                self.close()
                self._logger.info("meshtastic client is stopped by external command")

    @with_mutex("usb_port_mutex")
    def close(self):
        if not self._stop_signal.is_set():
            self._stop_signal.set()
        if self._interface:
            self._logger.debug(f"Closing interface {self._interface.myInfo}")
            self._interface.close()
            self._interface = None
        self._running = False

    def run(self):
        self._logger.debug(f"Starting meshtastic node thread: {self._node_config.short_name}")
        try:
            self._logger.debug(f"Trying connection to by wire: {self._node_config.short_name if self._node_config.short_name else "auto finding"}")
            self._interface = self._get_usb_interface()
        except Exception as exp:
            self._logger.exception(f"SerialInterface connection exception: {exp}")
            return
        self._running = True
        while True:
            if not self._stop_signal.is_set():
                try:
                    items = self._input_queue.get_batch(max_count=12)
                    if not items:
                        break
                    for cmd_type, data in items:
                        self._handle_command(cmd_type, data)
                    time.sleep(self._node_config.interval)
                except Exception as e:
                    self._logger.error(f"Error in thread: {self.name}, error: {e}")
            else:
                self._logger.debug(f"Closing the Meshtastic interface({self.name})")
                self.close()
                self._logger.info(f"{self.name} thread has finished execution")
                return

    @with_mutex("usb_port_mutex")
    def get_all_known_nodes_via_usb(self, sync_tryes_count: int = 10, sync_try_sleep_sec: float = 1.0) -> List[MeshtasticKnownNode]:
            for i in range(sync_tryes_count):
                if not self._interface.nodes:
                    self._logger.debug(f"[{i + 1}/{sync_tryes_count}]Syncing with node...")
                    time.sleep(sync_try_sleep_sec)
                else:
                    break
            if not self._interface.nodes:
                self._logger.critical("The node database is empty or has not yet loaded! Aborting!")
                raise MeshtasticWireException

            known_nodes_list: List[MeshtasticKnownNode] = []
            try:

                for node_id, raw_node in self._interface.nodes.items():
                    user_data = raw_node.get("user", {})
                    position_data = raw_node.get("position", {})

                    role = user_data.get("role")
                    if not _MODULE_CONSTS["ROLES_ALLOWED"].get(role, _MODULE_CONSTS["ROLES_ALLOWED"]["UNKNOWN_ROLE"]):
                        continue

                    # Extracting MAC-address
                    raw_mac = user_data.get("macaddr")
                    formatted_mac = self._bytes_to_mac_string(raw_mac)

                    # Datetime parsing
                    last_heard_timestamp = raw_node.get("lastHeard")
                    last_online_dt = (
                        datetime.fromtimestamp(last_heard_timestamp)
                        if last_heard_timestamp else None
                    )
                    last_online_str = last_online_dt.strftime(self._logger.detetime_fmt) if last_online_dt else ""

                    latitude = 0.0
                    longitude = 0.0
                    ch_a_aut_provides = False
                    uptime_seconds = altitude_meters = None
                    if position_data:
                        altitude_meters = position_data.get("altitude", -1)
                        latitude, longitude = (position_data.get("latitude"), position_data.get("longitude"))
                    if dev_metrics := raw_node.get("deviceMetrics"):
                        uptime_seconds = dev_metrics.get("uptimeSeconds", -1)
                        ch_a_aut_provides = dev_metrics.get("channelUtilization") and dev_metrics.get("airUtilTx")

                    is_valid_pos = self._node_config.real_position and all(c is not None for c in self._node_config.real_position)
                    is_valid_loc = (latitude, longitude) and (latitude, longitude) != (0, 0) and all(
                        c is not None for c in (latitude, longitude))

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
                        last_online=last_online_str,
                        messagable=user_data.get("isUnmessagable", False),
                        snr=raw_node.get("snr", None),
                        latitude=latitude,
                        longitude=longitude,
                        altitude_meters=altitude_meters,
                        _distance_km=self._calculate_geodistanse_in_km(self._node_config.real_position, (latitude, longitude)) if is_valid_pos and is_valid_loc else None,
                        mac_address=formatted_mac,
                        channelUtilization_airUtilTx_provides=ch_a_aut_provides,
                        favorite=user_data.get("isFavorite", False)
                        #additional_data=f"Battery: {position_data.get('batteryLevel', 'N/A')}%",
                    )
                    known_nodes_list.append(known_node)
            except MeshtasticWireException as mwe:
                self._logger.exception(f"MeshtasticWireException: {mwe}")
                raise
            except Exception as e:
                self._logger.exception(f"Exception: {e}")
                raise
            for node in known_nodes_list:
                try:
                    fetch_equals(MeshtasticKnownNode, field="id", value=node.id)
                    node.update_entry()
                except TypeError as e:
                    node.create_entry()
            return known_nodes_list

    def on_receive_message(self, packet, interface):
        try:
            if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
                message = packet['decoded']['text']
                sender = packet['fromId']
                self._output_queue.put(InternalQueuedItem(content={"message": message, "from": sender},
                                                          main_type="incoming_message"))
                self._logger.info(f"New message From: {sender}, Text: {message}")
        except Exception as e:
            self._logger.exception(f"Packet processing error: {e}")

