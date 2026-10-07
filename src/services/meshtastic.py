import json
import os
import threading
import time
import pathlib

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Tuple, Callable

from datalite.fetch import fetch_equals
from frozendict import frozendict
from meshtastic.serial_interface import SerialInterface
from geographiclib.geodesic import Geodesic
from datalite import datalite
from pubsub import pub

from src.log.loggers import EndpointLogger
from src.core.private_config import MeshtasticInternalNodeData
from src.core.structs import InternalQueuedItem, with_mutex

import serial.tools.list_ports
import meshtastic.serial_interface

from src.core.threading import IOQueuedThread, ThreadState

_MODULE_CONSTS = frozendict(RUNTIME_DIR=f"{pathlib.Path().resolve()}/meshtastic",
                            ROLES_ALLOWED=frozendict({
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


class MeshtasticWireException(Exception):
    pass


def mesh_json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


@datalite(db_path=f"{_MODULE_CONSTS["RUNTIME_DIR"]}/nodes.db")
@dataclass(eq=False)
class MeshtasticNode:
    short_name: str
    full_name: str
    public_key: str
    id: str
    device_name: str
    role: str
    mac_address: str = None
    favorite: bool = False

    @classmethod
    def _bytes_to_mac_string(cls, mac_bytes: Optional[bytes]) -> Optional[str]:
        if not mac_bytes or not isinstance(mac_bytes, bytes):
            return None
        return ":".join(f"{b:02X}" for b in mac_bytes)

    def __eq__(self, other):
        if not isinstance(other, MeshtasticNode):
            return NotImplemented
        return (self.short_name == other.short_name and
                self.id == other.id)

    def __hash__(self):
        return hash((self.short_name, self.public_key))


@datalite(db_path=f"{_MODULE_CONSTS["RUNTIME_DIR"]}/nodes.db")
@dataclass(eq=False)
class MeshtasticNodeMetrics:
    public_key: str
    short_name: str
    hopes: int = 0
    last_online: str = None
    uptime_seconds: int = None
    messagable: bool = None
    latitude: float = None
    longitude: float = None
    altitude_meters: int = None
    snr: float = None
    channelUtilization: float = None
    airUtilTx: float = None
    _timestramp: str = None
    _distance_km: float = None
    _additional_data: str = None

    def __hash__(self):
        return hash((self.short_name, self._timestramp, self.public_key))

    @classmethod
    def _calculate_geodistanse_in_km(cls, point_1: Tuple[float, float], point_2: Tuple[float, float]) -> float:
        return round(Geodesic.WGS84.Inverse(point_1[0], point_1[1], point_2[0], point_2[1])["s12"]/1000, 3)


class MeshtasticWireHandleThread(IOQueuedThread):

    _PORT_DESCRIPTION = "USB JTAG/serial debug unit"
    _PORT_VID = 12346
    _TEXT_MESSAGE_TYPE = "TEXT_MESSAGE_APP"

    def __init__(self, logger: EndpointLogger, config: MeshtasticInternalNodeData):
        super().__init__(logger, config.instance_config)
        self._usb_port_mutex = threading.Lock()
        self._config = config
        self._interface = None
        pub.subscribe(self.on_receive_message, "meshtastic.receive")

    def on_receive_message(self, packet, interface):
        try:
            if 'decoded' in packet and packet['decoded']['portnum'] == self._TEXT_MESSAGE_TYPE:
                message = packet['decoded']['text']
                sender = packet['fromId']
                self._output_queue.put(InternalQueuedItem(content={"message": message, "from": sender},
                                                          main_type="incoming_message"))
                self._logger.info(f"New message from: {sender}, text: {message}")
        except Exception as e:
            self._logger.exception(f"Message receiving exception: {e}")

    @property
    def usb_port_mutex(self) -> threading.Lock:
        return self._usb_port_mutex

    def _parse_node_data(self, node_id, raw) -> Tuple[MeshtasticNode, MeshtasticNodeMetrics]:
        user_data = raw.get("user", {})
        node = MeshtasticNode(
            short_name=user_data.get("shortName", "????"),
            full_name=user_data.get("longName", "UNKNOWN"),
            device_name=user_data.get("hwModel", "UNKNOWN_HW"),
            public_key=user_data.get("publicKey", "UNKNOWN"),
            id = node_id,
            role = user_data.get("role"),
            favorite = user_data.get("isFavorite", False)
        )
        if raw_mac := user_data.get("macaddr", ""):
            node.mac_address = node._bytes_to_mac_string(raw_mac)
        metric = MeshtasticNodeMetrics(
            public_key=node.public_key,
            short_name=node.short_name,
            hopes=raw.get("hopsAway", -1),
        )
        if last_heard := raw.get("lastHeard"):
            metric.last_online = self._logger.strftime(datetime.fromtimestamp(last_heard))
        metric.messagable = user_data.get("isUnmessagable", False)
        metric.snr = raw.get("snr")
        if dev_metrics := raw.get("deviceMetrics"):
            metric.uptime_seconds = dev_metrics.get("uptimeSeconds")
            metric.channelUtilization = dev_metrics.get("channelUtilization", 0.0)
            metric.airUtilTx = dev_metrics.get("airUtilTx", 0.0)
        if position_data := raw.get("position"):
            metric.altitude_meters = position_data.get("altitude")
            metric.latitude = position_data.get("latitude")
            metric.longitude = position_data.get("longitude")
        if self._config.real_position and metric.longitude and metric.longitude:
            metric._distance_km = metric._calculate_geodistanse_in_km(self._config.real_position, (metric.longitude, metric.longitude))
        metric._timestramp = self._logger.strftime_now()
        #metric.additional_data = f"Battery: {position_data.get('batteryLevel', 'N/A')}%"
        return (node, metric)

    def _save_nodes_info(self, nodes_info: List[MeshtasticNode | MeshtasticNodeMetrics]) -> None:
        for node in nodes_info:
            model_class = type(node)
            try:
                existing_entry = fetch_equals(model_class, field="public_key", value=node.public_key)
                node.obj_id = existing_entry.obj_id
                node.update_entry()
            except (TypeError, AttributeError):
                try:
                    node.create_entry()
                except Exception as e:
                    self._logger.exception()
                    print(f"Failed to create a record type: {model_class} for the ID: {node.short_name}: {e}")

    @with_mutex("usb_port_mutex")
    def get_all_known_nodes(self, sync_tries_count: int = 3, sync_try_sleep_sec: float = 1.0) -> List[MeshtasticNode]:
            for i in range(sync_tries_count):
                if not self._interface.nodes:
                    self._logger.debug(f"[{i + 1}/{sync_tries_count}]Syncing with node...")
                    time.sleep(sync_try_sleep_sec)
                else:
                    break
            if not self._interface.nodes:
                raise MeshtasticWireException("The node database is empty or has not yet loaded! Aborting!")
            nodes_list: List[MeshtasticNode] = []
            nodes_metrics_list: List[MeshtasticNodeMetrics] = []
            try:
                for node_id, raw in self._interface.nodes.items():

                    if not _MODULE_CONSTS["ROLES_ALLOWED"].get(raw.get("user", {}).get("role"), _MODULE_CONSTS["ROLES_ALLOWED"]["UNKNOWN_ROLE"]):
                        continue
                    node, metric = self._parse_node_data(node_id, raw)
                    nodes_list.append(node)
                    nodes_metrics_list.append(metric)
            except MeshtasticWireException as mwe:
                self._logger.exception(f"MeshtasticWireException: {mwe}")
                raise
            except Exception as e:
                self._logger.exception(f"Exception: {e}")
                raise
            self._save_nodes_info(nodes_list)
            self._save_nodes_info(nodes_metrics_list)
            return nodes_list

    def save_dumped_nodes(self, nodes: List[MeshtasticNode]):
        os.makedirs(_MODULE_CONSTS["RUNTIME_DIR"], exist_ok=True)
        with open(f"{_MODULE_CONSTS["RUNTIME_DIR"]}/known_nodes_dump_{self._logger.strftime_now(safe_format=True)}.json",
                  "w+") as f:
            f.write(self._json_format_dumped_nodes(nodes))

    @classmethod
    def json_dumps_nodes(cls, nodes: List[MeshtasticNode|MeshtasticNodeMetrics]) -> str:
        return json.dumps([asdict(node) for node in nodes], default=mesh_json_serial, ensure_ascii=False, indent=4)

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
            if current_short_name == self._config.short_name:
                self._logger.debug(f"Interface {self._config.short_name} found")
                return interface
        if usb_ports:
            self._logger.critical(f"Interface {self._config.short_name} not found, using first another interface")
            return meshtastic.serial_interface.SerialInterface(
                devPath=usb_ports[0].device,
                connectNow=True
            )
        raise NameError("No nodes connected via USB were found")

    @with_mutex("usb_port_mutex")
    def send_message(self, text: str, channel: int = 0, destinationId: int = -1) -> None:
        self._logger.debug(f"Trying connection to by wire - {self._config.short_name if self._config.short_name else "auto finding"}")
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

    def run(self):
        super().run()
        try:
            self._logger.debug(f"Trying connection to by wire: {self._config.short_name if self._config.short_name else "auto finding"}")
            self._interface = self._get_usb_interface()
        except Exception as exp:
            self._logger.exception(f"SerialInterface connection exception: {exp}")
            self._state = ThreadState.ERROR_DOWN
            return
        try:
            while not self._stop_signal.is_set():
                    time.sleep(self._config.instance_config.interval)
                    try:
                        items = self._input_queue.get_batch(max_count=12)
                        if not items:
                            continue
                        for cmd_type, data in items:
                            self._handle_command(cmd_type, data)
                    except Exception as e:
                        self._logger.error(f"Error: {e}")
        finally:
            self._logger.debug(f"Closing the Meshtastic interface({self.name})")
            self.close()
            self._logger.info(f"{self.name} thread has finished execution")

    @with_mutex("usb_port_mutex")
    def close(self):
        if not self._stop_signal.is_set():
            self._stop_signal.set()
        if self._interface:
            self._logger.debug(f"Closing interface {self._interface.myInfo}")
            self._interface.close()
            self._interface = None

    @with_mutex("mutex")
    def finalize(self):
        super().finalize()
        self.close()
