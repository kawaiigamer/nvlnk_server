import threading
import queue
from typing import Tuple, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from server_logging import EndpointLogger
from server_private import ToxClientConfig
from server_queue import LimitedTypedQueue, InternalQueuedItem

import os
import ctypes
import time

_PRIVATE_TOX_PATH = "tox_library"


class ToxInterlocutorNotOnlineException(BaseException):
    pass


class ToxCCoreException(BaseException):
    pass


class ToxClientThread(threading.Thread):
    def __init__(self, logger: EndpointLogger, config: ToxClientConfig):
        super().__init__()
        self._logger = logger
        self._running = False
        self._lock = threading.Lock()
        self.cmd_queue = queue.Queue()
        self.events_queue = LimitedTypedQueue[InternalQueuedItem](logger, max_size=config.queue_max_size, name="Tox")
        self.config = config
        self.tox_lib = None
        self.tox_instance = None
        self.tox_public_key = None
        self._init_tox_native_library()

    def __call__(self):
        self.run()

    def _init_tox_native_library(self) -> None:
        native_dll_path = os.path.join(os.getcwd(), _PRIVATE_TOX_PATH)
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(native_dll_path)
        try:
            lib_path = os.path.join(native_dll_path, "libtoxcore.dll")
            tox_lib = ctypes.CDLL(lib_path)
            self._logger.info("Native DLL libtoxcore.dll loaded")
        except Exception as e:
            self._logger.error(f"Native DLL libtoxcore.dll loading error: {e}")
            raise
        self.TOX_SAVEDATA_TYPE_TOX_SAVE = 1
        self.TOX_SAVEDATA_TYPE_SECRET_KEY = 2
        self.TOX_ERR_FRIEND_SEND_MESSAGE_FRIEND_NOT_CONNECTED = 2

        # tox save data
        tox_lib.tox_options_new.restype = ctypes.c_void_p
        tox_lib.tox_options_new.argtypes = [ctypes.c_void_p]
        tox_lib.tox_options_set_savedata_type.restype = None
        tox_lib.tox_options_set_savedata_type.argtypes = [ctypes.c_void_p, ctypes.c_int]
        tox_lib.tox_options_set_savedata_data.restype = None
        tox_lib.tox_options_set_savedata_data.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_size_t
        ]
        # tox_new
        tox_lib.tox_new.restype = ctypes.c_void_p
        tox_lib.tox_new.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        # tox_self_get_address
        tox_lib.tox_self_get_address.restype = None
        tox_lib.tox_self_get_address.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        # tox_bootstrap
        tox_lib.tox_bootstrap.restype = ctypes.c_bool
        tox_lib.tox_bootstrap.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint16, ctypes.c_char_p,
                                          ctypes.c_void_p]
        # tox_iteration_interval
        tox_lib.tox_iteration_interval.restype = ctypes.c_uint32
        tox_lib.tox_iteration_interval.argtypes = [ctypes.c_void_p]
        # tox_iterate
        tox_lib.tox_iterate.restype = None
        tox_lib.tox_iterate.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        # tox_self_get_connection_status
        tox_lib.tox_self_get_connection_status.restype = ctypes.c_int
        tox_lib.tox_self_get_connection_status.argtypes = [ctypes.c_void_p]
        tox_lib.tox_friend_add_norequest.restype = ctypes.c_uint32
        tox_lib.tox_friend_add_norequest.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
        # Checking friend status (online/offline)
        tox_lib.tox_friend_get_connection_status.restype = ctypes.c_int
        tox_lib.tox_friend_get_connection_status.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        # Sending message
        tox_lib.tox_friend_send_message.restype = ctypes.c_uint32
        tox_lib.tox_friend_send_message.argtypes = [
            ctypes.c_void_p,  # инстанс
            ctypes.c_uint32,  # порядковый номер друга в списке (friend_number)
            ctypes.c_int,  # тип сообщения (0 = нормальное текстовое)
            ctypes.POINTER(ctypes.c_char),  # текст сообщения в байтах
            ctypes.c_size_t,  # длина текста
            ctypes.c_void_p  # указатель на код ошибки
        ]
        # Incoming message
        tox_lib.tox_callback_friend_message.restype = None
        tox_lib.tox_callback_friend_message.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        # C-function prototype for an incoming message
        self.TOX_FRIEND_MESSAGE_CB = ctypes.CFUNCTYPE(
            None,  # Возвращаемое значение (void)
            ctypes.c_void_p,  # инстанс tox
            ctypes.c_uint32,  # номер друга friend_number
            ctypes.c_int,  # тип сообщения (0 = обычное)
            ctypes.POINTER(ctypes.c_char),  # указатель на текст сообщения в байтах
            ctypes.c_size_t,  # длина сообщения length
            ctypes.c_void_p  # кастомные пользовательские данные user_data
        )
        self.on_incoming_message_func = self.TOX_FRIEND_MESSAGE_CB(self.on_incoming_message)

        self.tox_lib = tox_lib

    def is_running(self) -> bool:
        return self._running

    def on_incoming_message(self, tox_instance, friend_number, message_type, message_ptr, length, user_data):
        try:
            raw_message = ctypes.string_at(message_ptr, length)
            text = raw_message.decode('utf-8')
            self._logger.info(f"Incoming message From: {friend_number}, Text: {text}")
            self.events_queue.put(InternalQueuedItem(content={"text": text, "message_type": message_type, "from": friend_number},
                                                     main_type="incoming"))
        except Exception as e:
            self._logger.error(f"Exception inside the incoming message processing callback: {e}")

    def run(self):
        self._logger.debug("Starting client tox_library thread")

        options = self.tox_lib.tox_options_new(None)
        if not options:
            self._logger.error("Failed to create Tox Options")
            return

        key_bytes = bytes.fromhex(self.config.private_key)
        data_len = len(key_bytes)
        c_array = (ctypes.c_char * data_len)(*key_bytes)
        c_ptr = ctypes.cast(c_array, ctypes.POINTER(ctypes.c_char))
        self._logger.debug("Binding the raw private key to boot options")
        self.tox_lib.tox_options_set_savedata_type(options, self.TOX_SAVEDATA_TYPE_SECRET_KEY)
        self.tox_lib.tox_options_set_savedata_data(options, c_ptr, ctypes.c_size_t(data_len))

        err = ctypes.c_int(0)
        self.tox_instance = self.tox_lib.tox_new(options, ctypes.byref(err))
        if not self.tox_instance:
            self._logger.core(f"Error while creating Tox instance. C-Core Error Code: {err.value}")
            return
        self._logger.debug("The Tox instance has been launched directly from your private key")

        address_buffer = ctypes.create_string_buffer(38)
        self.tox_lib.tox_self_get_address(self.tox_instance, address_buffer)
        self.tox_public_key = address_buffer.raw.hex().upper()
        self._logger.info(f"Final tox public key(TOX ID):{self.tox_public_key}")

        node_ip = b"nodes.tox.chat"
        node_port = 33445
        node_key_bytes = bytes.fromhex("3091C6BEB2A993F1C6300EE1B91392A7A446CE1A7C3D3CFE3A4BCEAA01C98725")
        self.tox_lib.tox_bootstrap(self.tox_instance, node_ip, node_port, node_key_bytes, None)
        self._logger.debug(f"Connecting to a DHT node: {node_ip.decode()}")
        success = self.tox_lib.tox_bootstrap(self.tox_instance, node_ip, node_port, node_key_bytes, None)
        if not success:
            self._logger.core("Bootstrap failed...")
            return
        self._running = True
        self._logger.info("Tox client is running in the background thread...")

        if self.config.interval is None:
            sleep_interval = self.tox_lib.tox_iteration_interval(self.tox_instance) / 1000.0
        else:
            sleep_interval = self.config.interval
        self._logger.debug(f"Tox client sleep interval: {sleep_interval} sec")

        connected_flag: bool = False
        while self._running:
            self.tox_lib.tox_iterate(self.tox_instance, None)

            status = self.tox_lib.tox_self_get_connection_status(self.tox_instance)
            if status > 0 and not connected_flag:
                self._logger.info(f"Successfully connected to the Tox network! Current status: {status}")
                connected_flag = True
            elif status == 0 and connected_flag:
                self._logger.error("Tox network connection lost")
                connected_flag = False

            try:
                while not self.cmd_queue.empty():
                    cmd_type, data = self.cmd_queue.get_nowait()
                    self._handle_command(cmd_type, data)
                    self.cmd_queue.task_done()
            except queue.Empty:
                pass
            time.sleep(sleep_interval)

    def _send_message(self, friend_number: str, message: str) -> int:
        self._logger.debug(f"Trying send message Text: {message}, To: {friend_number}")
        friend_pk_bytes = bytes.fromhex(friend_number[:64])
        friend_err = ctypes.c_int(0)
        friend_number = self.tox_lib.tox_friend_add_norequest(self.tox_instance, friend_pk_bytes, ctypes.byref(friend_err))
        self._logger.debug(f"The interlocutor is registered under number: {friend_number}")

        f_err = ctypes.c_int(0)
        friend_status = self.tox_lib.tox_friend_get_connection_status(self.tox_instance, friend_number, ctypes.byref(f_err))
        if friend_status > 0:
            self._logger.debug("The interlocutor person is online, sending message")
            message_bytes = message.encode('utf-8')
            message_len = len(message_bytes)
            c_array = (ctypes.c_char * message_len)(*message_bytes)
            c_ptr = ctypes.cast(c_array, ctypes.POINTER(ctypes.c_char))
            err = ctypes.c_int(0)
            msg_id = self.tox_lib.tox_friend_send_message(
                self.tox_instance,
                friend_number,
                0,
                c_ptr,
                ctypes.c_size_t(message_len),
                ctypes.byref(err)
            )
            if msg_id == 0xFFFFFFFF or err.value != 0:
                self._logger.exception(f"Failed to send the message. C-Core error code: {err.value}")
                if err.value == self.TOX_ERR_FRIEND_SEND_MESSAGE_FRIEND_NOT_CONNECTED:
                    self._logger.exception("The interlocutor is currently offline. Message cannot be delivered")
                    raise ToxInterlocutorNotOnlineException()
                else:
                    raise ToxCCoreException(str(err.value))
            else:
                self._logger.debug(f"Message sent, message ID: {msg_id}")
                return msg_id

    def _handle_command(self, cmd_type: str, data: Optional[Tuple[str, str]]):
        if cmd_type == "send_msg":
            friend_number, message_text = data
            event_content = {"friend_number": friend_number, "message_text": message_text}
            event_main_type = "outgoing"
            try:
                event_content["msg_id"] = self._send_message(friend_number, message_text)
            except ToxInterlocutorNotOnlineException:
                event_sub_type = "Tox interlocutor not online"
            except ToxCCoreException as tcce:
                event_sub_type = f"Tox core exception {tcce}"
            except Exception as e:
                self._logger.exception(f"Message sending error, Text: {message_text} sent to {friend_number}, Exception: {e}")
                event_sub_type=f"Sending exception: {e}"
            else:
                event_sub_type = "Message sent"
            self.events_queue.put(InternalQueuedItem(content=event_content,
                                                     main_type=event_main_type,
                                                     sub_type=event_sub_type))
        elif cmd_type == "stop":
            self._running = False
            self._logger.info("Tox client stopped by external command")

    def send_message_safely(self, friend_number: int, message: str):
        self._logger.debug("send_msg command received")
        self.cmd_queue.put(("send_msg", (friend_number, message)))

    def stop_safely(self):
        self._logger.debug("Stop command received")
        self.cmd_queue.put(("stop", None))
