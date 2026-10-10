import base64
import json
import os
import threading
import time
import pathlib
from enum import unique, Enum

import serial.tools.list_ports

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Tuple, Literal, Dict, Any, Union, Set

from datalite.fetch import fetch_if
from frozendict import frozendict
from meshtastic.serial_interface import SerialInterface
from geographiclib.geodesic import Geodesic
from datalite import datalite
from pubsub import pub

from src.log.loggers import MiddlewareLogger
from src.core.private_config import MeshtasticInternalNodeData
from src.core.structs import InternalQueuedItem, with_mutex
from src.core.core_threading import IOQueuedThread, ThreadState

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
    taken_from: str
    role: str
    device_model: str = None
    mac: str = None
    favorite: bool = False
    _timestramp: str = None

    @classmethod
    def _mac_to_hex(cls, mac_b64: str) -> str:
        return ":".join(f"{b:02X}" for b in base64.b64decode(mac_b64))

    def __eq__(self, other):
        if not isinstance(other, MeshtasticNode):
            return NotImplemented
        return (self.short_name == other.short_name and
                self.id == other.id and self.taken_from == other.taken_from)

    def __hash__(self):
        return hash((self.short_name, self.public_key, self.taken_from))


@datalite(db_path=f"{_MODULE_CONSTS["RUNTIME_DIR"]}/nodes.db")
@dataclass(eq=False)
class MeshtasticNodeMetrics:
    public_key: str
    short_name: str
    taken_from: str
    hopes: int = None
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
        return hash((self.short_name, self._timestramp, self.public_key, self.taken_from))

    @classmethod
    def _calculate_geodistanse_in_km(cls, point_1: Tuple[float, float], point_2: Tuple[float, float]) -> float:
        return round(Geodesic.WGS84.Inverse(point_1[0], point_1[1], point_2[0], point_2[1])["s12"]/1000, 3)

@unique
class MeshtasticMessageDirection(Enum):
    UNKNOWN = -1
    IGNORED = 0
    OUTGOING = 1
    INCOMING = 2


@datalite(db_path=f"{_MODULE_CONSTS["RUNTIME_DIR"]}/messages.db")
@dataclass(eq=False)
class MeshtasticMessage:
    message_uid: int
    from_id: str
    to_id: str
    channel: int
    hops: int
    direction: int
    transport: str = None
    bitfield: int = None
    type: str = None
    text: str = None
    delivered: bool = None
    _taken_from: str = None
    _timestramp: str = None

    def __hash__(self):
        return hash((self.message_uid, self._timestramp, self._taken_from))

    def __eq__(self, other):
        if not isinstance(other, MeshtasticMessage):
            return NotImplemented
        return (self.message_uid == other.message_uid and
                self._taken_from == other._taken_from)


class MeshtasticWireHandleThread(IOQueuedThread):

    _PORT_DESCRIPTION = "USB JTAG/serial debug unit"
    _PORT_VID = 12346
    _TEXT_MESSAGE_TYPE = "TEXT_MESSAGE_APP"
    _BROADCAST_IND: int = 0xffffffff
    _LORA_TRANSPORT_IND: str = "TRANSPORT_LORA"

    def __init__(self, logger: MiddlewareLogger, config: MeshtasticInternalNodeData):
        super().__init__(logger, config.instance_config)
        self._usb_port_mutex = threading.Lock()
        self._config = config
        self._interface = None
        self._pending_packet_ids: Set[int] = set()
        pub.subscribe(self.on_receive_message, "meshtastic.receive")

    def _try_update_outgoing_message_status(self, uid: int, packet: Dict[str, Union[str, bytes, int, Dict]]) -> None:
        try:
            content = {"message_uid": uid}
            if pending_error := packet.get("routing", {}).get("errorReason"):
                self._logger.warning(f"Message with uid: {uid} could not be delivered. Reason: {pending_error}")
                content["status"] = "Error"
                content["reason"] = pending_error
            else:
                self._logger.info(f"Message with uid: {uid} delivered successfully to destination node")
                content["status"] = "Success"
            self._output_queue.put(InternalQueuedItem(content=content, main_type="outgoing_message_status"))
            self._pending_packet_ids.remove(uid)
            self._logger.debug(f"Updating status of message with uid: {uid} in db")
            if fetchable_messages := fetch_if(MeshtasticMessage, f"message_uid = '{uid}'"):
                if fetchable_messages[0].delivered is None:
                    fetchable_messages[0].delivered = content["status"] == "Success"
                    fetchable_messages[0].update_entry()
                    self._logger.info(f"Message with uid: {uid} marked as successfully delivered in db")
                else:
                    self._logger.warning(f"Message with uid: {uid} was already marked {'' if fetchable_messages[0].delivered else 'not'} delivered in db")
            else:
                self._logger.attention(f"Message with uid: {uid} not found in db")
        except Exception as e:
            self._logger.exception(f"Exception while parsing error reason from received routing pachet: {e}")

    @with_mutex("mutex")
    def on_receive_message(self, packet: Dict[str, Union[str, bytes, int, Dict]], interface) -> None:
        uid: int = packet.get('id', 0)
        if uid in self._pending_packet_ids:
            self._try_update_outgoing_message_status(uid, packet)
            return
        if not 'decoded' in packet or packet.get('decoded', {}).get('portnum') != self._TEXT_MESSAGE_TYPE:
            return
        if self._config.only_lora and packet['transportMechanism'] != self._LORA_TRANSPORT_IND:
            return
        try:
                decoded: Dict[str, Union[str, bytes, int]] = packet['decoded']
                parsed_kwargs = {"from_id": packet.get('fromId'), "to_id": "BROADCAST" if packet['to'] == self._BROADCAST_IND else packet.get('toId'),
                                 "channel": packet.get('channel'), "hops": packet.get('hopStart', 0) - packet.get('hopLimit', 0), "transport": packet.get('transportMechanism'),
                                 "bitfield": decoded.get('bitfield'), "type": decoded.get('portnum'), "text": decoded.get("text"), "delivered": True}
                message = MeshtasticMessage(message_uid=uid, _taken_from=self._config.short_name,
                                            _timestramp=self._logger.strftime_now(), direction=MeshtasticMessageDirection.INCOMING.value,
                                                                                               **parsed_kwargs)
                message.create_entry()
                self._output_queue.put(InternalQueuedItem(content=parsed_kwargs, main_type="incoming_message"))
                self._logger.notify(f"New message: {parsed_kwargs}")
        except (ValueError, TypeError) as e:
            self._logger.exception(f"Received pachet parsing exception: {e}")
        except Exception as other_e:
            self._logger.exception(f"Other exception while parsing received pachet: {other_e}")

    @property
    def usb_port_mutex(self) -> threading.Lock:
        return self._usb_port_mutex

    def _parse_node_data(self, node_id: str, raw: Dict[str, Any]) -> Tuple[MeshtasticNode, MeshtasticNodeMetrics]:
        user_data = raw.get("user", {})
        timestramp: str = self._logger.strftime_now()
        node = MeshtasticNode(
            short_name=user_data.get("shortName", "????"),
            full_name=user_data.get("longName", "UNKNOWN"),
            public_key=user_data.get("publicKey", "UNKNOWN"),
            id=node_id,
            taken_from=self._config.short_name,
            device_model=user_data.get("hwModel"),
            role=user_data.get("role", "UNKNOWN_ROLE"),
            favorite=user_data.get("isFavorite", False),
            _timestramp=timestramp
        )
        if mac_b64 := user_data.get("macaddr"):
            node.mac = node._mac_to_hex(mac_b64)
        metric = MeshtasticNodeMetrics(
            public_key=node.public_key,
            short_name=node.short_name,
            taken_from=self._config.short_name,
            hopes=raw.get("hopsAway"),
            _timestramp=timestramp
        )
        if last_heard := raw.get("lastHeard"):
            metric.last_online = self._logger.strftime(datetime.fromtimestamp(last_heard))
        metric.messagable = user_data.get("isUnmessagable", False)
        metric.snr = raw.get("snr")
        if dev_metrics := raw.get("deviceMetrics"):
            metric.uptime_seconds = dev_metrics.get("uptimeSeconds")
            metric.channelUtilization = dev_metrics.get("channelUtilization")
            metric.airUtilTx = dev_metrics.get("airUtilTx")
        if position_data := raw.get("position"):
            metric.altitude_meters = position_data.get("altitude")
            metric.latitude = position_data.get("latitude")
            metric.longitude = position_data.get("longitude")
        if self._config.real_position and metric.longitude and metric.longitude:
            metric._distance_km = metric._calculate_geodistanse_in_km(self._config.real_position, (metric.latitude, metric.longitude))
        #metric.additional_data = f"Battery: {position_data.get('batteryLevel', 'N/A')}%"
        return (node, metric)

    @classmethod
    def __create_fetch_condition(cls, item: MeshtasticNode | MeshtasticNodeMetrics, order: Literal["DESC", "AESC"] = "DESC", limit: int = 1) -> str:
        return f"short_name = '{item.short_name}' AND public_key = '{item.public_key}' AND taken_from = '{item.taken_from}' ORDER BY obj_id {order} LIMIT {limit}"

    def _save_nodes_records(self, nodes_records: List[MeshtasticNode | MeshtasticNodeMetrics]) -> None:
        for record in nodes_records:
            try:
                if isinstance(record, MeshtasticNode):
                    if fetchable_nodes := fetch_if(MeshtasticNode, self.__create_fetch_condition(record)):
                        delta: float = (self._logger.strptime(record._timestramp) - self._logger.strptime(fetchable_nodes[0]._timestramp)).total_seconds()
                        if delta < self._config.new_node_add_delta_sec:
                            continue
                    record.create_entry()
                elif isinstance(record, MeshtasticNodeMetrics):
                    if fetchable_metrics := fetch_if(MeshtasticNodeMetrics, self.__create_fetch_condition(record)):
                        delta: float = (self._logger.strptime(record._timestramp) - self._logger.strptime(fetchable_metrics[0]._timestramp)).total_seconds()
                        if delta < self._config.new_metrics_add_delta_sec:
                            continue
                    record.create_entry()
            except (TypeError, AttributeError) as ex:
                self._logger.exception(f"Failed to create/update a record type: {type(record)} with ID: {record.short_name}: {ex}")

    def _get_raw_nodes(self, sync_tries_count: int = 3, sync_tries_sleep_sec: float = 1.0) -> Dict[str, Dict[str, Any]]:
        self._logger.external(f"Starting synchronization with node")
        for i in range(sync_tries_count):
            time.sleep(sync_tries_sleep_sec)
            if self._interface.nodes:
                return self._interface.nodes
            self._logger.attention(f"Synchronization try({i + 1}/{sync_tries_count}) is overed, but probably synchronization process ended with some errors, trying again")
        raise MeshtasticWireException("The node database is empty or has not yet loaded! Aborting!")

    @with_mutex("usb_port_mutex")
    def get_all_known_nodes(self, sync_tries_count: int = 3, sync_tries_sleep_sec: float = 1.0) -> List[MeshtasticNode]:
        raw_nodes_data: Dict[str, Dict[str, Any]] = self._get_raw_nodes(sync_tries_count, sync_tries_sleep_sec)
        self._logger.external(f"Successfully synchronized with node")
        nodes: List[MeshtasticNode] = []
        nodes_metrics: List[MeshtasticNodeMetrics] = []
        try:
            for node_id, raw in raw_nodes_data.items():
                if not _MODULE_CONSTS["ROLES_ALLOWED"].get(raw.get("user", {}).get("role"),
                                                           _MODULE_CONSTS["ROLES_ALLOWED"]["UNKNOWN_ROLE"]):
                    continue
                node, metric = self._parse_node_data(node_id, raw)
                nodes.append(node)
                nodes_metrics.append(metric)
        except MeshtasticWireException as mwe:
            self._logger.exception(f"MeshtasticWireException: {mwe}")
            raise
        except Exception as e:
            self._logger.exception(f"Exception: {e}")
            raise
        self._save_nodes_records(nodes + nodes_metrics)
        return nodes

    @classmethod
    def json_dumps_nodes(cls, nodes: List[MeshtasticNode|MeshtasticNodeMetrics]) -> str:
        return json.dumps([asdict(node) for node in nodes], default=mesh_json_serial, ensure_ascii=False, indent=4)

    @with_mutex("usb_port_mutex")
    def _get_usb_interface(self) -> Optional[SerialInterface]:
        ports = serial.tools.list_ports.comports()
        self._logger.debug(f"Founded {len(ports)} serial ports")
        usb_ports = []
        for port in ports:
            if port.description.startswith(self._PORT_DESCRIPTION) and port.vid == self._PORT_VID:
                usb_ports.append(port)
        self._logger.system(f"Founded {len(usb_ports)} devices: {[up.device for up in usb_ports]} with expected description({self._PORT_DESCRIPTION}) and vid({self._PORT_VID})")
        for usb_port in usb_ports:
            interface = SerialInterface(
                devPath=usb_port.device,
                connectNow=True
            )
            my_node = interface.getMyNodeInfo()
            current_short_name = my_node.get('user', {}).get('shortName')
            if current_short_name == self._config.short_name:
                self._logger.system(f"Interface for {self._config.short_name} was found!")
                return interface
        if usb_ports:
            self._logger.critical(f"Interface {self._config.short_name} not found, using first another interface")
            return SerialInterface(
                devPath=usb_ports[0].device,
                connectNow=True
            )
        raise NameError("No nodes connected via USB were found")

    @with_mutex("usb_port_mutex")
    def _send_message(self, text: str, channel: int = 0, destinationId: int = _BROADCAST_IND) -> int:
        self._logger.debug(f"Trying sending message by Lora - {self._config.short_name if self._config.short_name else "auto finding"}")
        content_kwargs = {"direction": MeshtasticMessageDirection.OUTGOING.value, "text": text,
                          "channel": channel, "from_id": self._config.short_name, "hops": 0,
                          "transport": self._LORA_TRANSPORT_IND,
                          "bitfield": 1, "type": self._TEXT_MESSAGE_TYPE, "_taken_from": self._config.short_name,
                          "_timestramp": self._logger.strftime_now()}
        try:
            self._logger.external(f"Trying to send message Text: {text} Channel: {channel}, destinationId: {destinationId}")

            if destinationId == self._BROADCAST_IND:
                content_kwargs["message_uid"] = self._pending_packet_ids.add(self._interface.sendText(text, channelIndex=channel).get("id", 0))
                content_kwargs["to_id"] = "BROADCAST"
            else:
                content_kwargs["message_uid"] = self._pending_packet_ids.add(self._interface.sendText(text, destinationId=destinationId).get("id", 0))
                content_kwargs["to_id"] = str(destinationId)
            self._logger.info(f"Message {text} is sending now!")
            message = MeshtasticMessage(**content_kwargs)
            message.create_entry()
        except MeshtasticWireException as mwe:
            self._logger.exception(f"MeshtasticWireException: {mwe}")
            raise
        finally:
            return content_kwargs.get("message_uid", 0)
    def run(self):
        super().run()
        try:
            self._logger.external(f"Trying connection to by wire: {self._config.short_name if self._config.short_name else "auto finding"}")
            self._interface = self._get_usb_interface()
        except Exception as exp:
            self._logger.exception(f"SerialInterface connection exception: {exp}")
            self._state = ThreadState.EXTERNAL_ERROR_DOWN
            return
        try:
            while not self._stop_signal.is_set():
                    time.sleep(self._config.instance_config.interval)
                    self._statistics.time.idle_seconds += self._config.instance_config.interval
                    try:
                        for item in self._input_queue.get_batch(max_count=4):
                            self._handle_command(item)
                    except Exception as e:
                        self._logger.exception(f"Other exception: {e}")
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
        self._pending_packet_ids.clear()
        self.close()

    def _handle_command(self, item: InternalQueuedItem) -> None:
        if item.main_type != "command":
            self._logger.warning(f"Skipping not command item: {item.to_json()}")
            return
        match item.sub_type:
            case "send_message":
                content_kwargs = item.content.copy()
                try:
                    content_kwargs["message_uid"] = self._send_message(**item.content)
                except MeshtasticWireException as e:
                    content_kwargs["status"] = f"MeshtasticWireException: {e}"
                except Exception as e:
                    content_kwargs["status"] = f"Other sending exeption: {e}"
                else:
                    content_kwargs["status"] = f"Pending"
                self._output_queue.put(InternalQueuedItem(content=content_kwargs,
                                                          main_type="command_status",
                                                          sub_type="send_message"))

            case "stop":
                self.finalize()

    def send_message_command(self, text: str, channel: int = 0, destinationId: int = _BROADCAST_IND) -> None:
        self._input_queue.put(InternalQueuedItem(
                content={"text": text, "channel": channel, "destinationId": destinationId},
                main_type="command",
                sub_type="send_message"
        ))
        self._logger.notify("send_message command accepted")

    def stop_command(self) -> None:
        self._input_queue.put(InternalQueuedItem(
                content={},
                main_type="command",
                sub_type="stop"
        ))
        self._logger.notify("stop command accepted")
