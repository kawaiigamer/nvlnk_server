import os
import ctypes
import time
import threading
import pathlib
from dataclasses import dataclass
from typing import Tuple, Optional, List

from datalite import datalite
from datalite.fetch import fetch_equals
from frozendict import frozendict

from src.log.loggers import EndpointLogger
from src.core.private_config import ToxClientConfig
from src.core.structs import InternalQueuedItem, with_mutex
from src.core.threading import IOQueuedThread, ThreadState


class ToxInterlocutorNotOnlineException(Exception):
    pass


class ToxIOException(Exception):
    pass


class ToxCCoreException(Exception):
    pass


_MODULE_CONSTS = frozendict(UINT32_MAX=0xFFFFFFFF, RUNTIME_DIR=f"{pathlib.Path().resolve()}/tox", RUNTIME_PROFILE_FILENAME="default.tox",
                            RUNTIME_LIBRARY_DIR=f"{pathlib.Path().resolve()}/tox_library", RUNTIME_LIBRARY_FILENAME="libtoxcore.dll", PUBLIC_KEY_SIZE=32,
                            TEXT_MESSAGE_TYPE_DEFAULT=0, SAVEDATA_TYPE_SAVE=1, SAVEDATA_TYPE_SECRET_KEY=2,
                            FRIEND_NOT_CONNECTED_ONLINE_ERROR=2, CONNECTION_STATUSES={0: "Offline", 1: "Online (UDP)", 2: "Online (TCP)"})


@datalite(db_path=f"{_MODULE_CONSTS["RUNTIME_DIR"]}/nodes.db")
@dataclass
class ToxInterlocutor:
    public_key: str
    connection_status: str
    added_timestamp: str


class ToxClientThread(IOQueuedThread):
    def __init__(self, logger: EndpointLogger,  config: ToxClientConfig):
        super().__init__(logger, config.instance_config)
        self._io_mutex = threading.Lock()
        self._config = config
        self._tox_lib = self._init_tox_native_library()
        self._profile_file_path: str = os.path.join(os.getcwd(), _MODULE_CONSTS["RUNTIME_DIR"], _MODULE_CONSTS["RUNTIME_PROFILE_FILENAME"])
        self._tox_instance = None
        self._create_new_instance()
        self._public_key = self._extract_public_key()
        self._logger.info(f"Final tox public key(TOX ID): {self._public_key}")

    @property
    def io_mutex(self) -> threading.Lock:
        return self._io_mutex

    @property
    def public_key(self) -> Optional[str]:
        return self._public_key

    @with_mutex("mutex")
    def _init_tox_native_library(self) -> ctypes.CDLL:
        native_dll_path = os.path.join(os.getcwd(), _MODULE_CONSTS["RUNTIME_LIBRARY_DIR"])
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(native_dll_path)
        try:
            lib_path = os.path.join(native_dll_path, _MODULE_CONSTS["RUNTIME_LIBRARY_FILENAME"])
            tox_lib = ctypes.CDLL(lib_path)
            self._logger.system(f"Native {_MODULE_CONSTS["RUNTIME_LIBRARY_FILENAME"]} DLL loaded")
        except Exception as e:
            self._logger.critical(f"Native {_MODULE_CONSTS["RUNTIME_LIBRARY_FILENAME"]} DLL loading exception: {e}")
            raise
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
            ctypes.c_void_p,  # Tox instance
            ctypes.c_uint32,  # Friend's position in the list (friend_number)
            ctypes.c_int,  # Message type
            ctypes.POINTER(ctypes.c_char),  # Pointer to the message text in bytes
            ctypes.c_size_t,  # Text length
            ctypes.c_void_p  # Pointer to error code
        ]
        # Incoming message
        tox_lib.tox_callback_friend_message.restype = None
        tox_lib.tox_callback_friend_message.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        # C-function prototype for an incoming message
        self._friend_message_cb_prototype = ctypes.CFUNCTYPE(
            None,  # Return value (void)
            ctypes.c_void_p,  # Tox instance
            ctypes.c_uint32,  # Friend's position in the list (friend_number)
            ctypes.c_int,  # Message type
            ctypes.POINTER(ctypes.c_char),  # Pointer to the message text in bytes
            ctypes.c_size_t,  # Message length
            ctypes.c_void_p  # Custom user data
        )
        # Load saved data
        tox_lib.tox_get_savedata_size.restype = ctypes.c_size_t
        tox_lib.tox_get_savedata_size.argtypes = [ctypes.c_void_p]
        tox_lib.tox_get_savedata.restype = None
        tox_lib.tox_get_savedata.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8)]
        # tox_self_get_friend_list_size
        tox_lib.tox_self_get_friend_list_size.restype = ctypes.c_size_t
        tox_lib.tox_self_get_friend_list_size.argtypes = [ctypes.c_void_p]
        # tox_self_get_friend_list
        tox_lib.tox_self_get_friend_list.restype = None
        tox_lib.tox_self_get_friend_list.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        # tox_friend_get_public_key
        tox_lib.tox_friend_get_public_key.restype = ctypes.c_bool
        tox_lib.tox_friend_get_public_key.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                                                      ctypes.c_void_p]
        # Method to confirm or add a friend without sending a reciprocal request.
        tox_lib.tox_friend_add_norequest.restype = ctypes.c_uint32
        tox_lib.tox_friend_add_norequest.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
        # Callback registrar for friend requests
        tox_lib.tox_callback_friend_request.restype = None
        tox_lib.tox_callback_friend_request.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        # C prototype for the incoming friend request processing function
        self._friend_request_cb_prototype = ctypes.CFUNCTYPE(
            None,            # Return value (void)
            ctypes.c_void_p, # Tox instance
            ctypes.c_char_p, # Pointer to the sender's public key (32 bytes)
            ctypes.c_char_p, # Pointer to the welcome message text
            ctypes.c_size_t, # Welcome message length
            ctypes.c_void_p  # User data (user_data)
        )
        # -------------------------------------------------------
        self._logger.debug(f"Native ctypes from {_MODULE_CONSTS["RUNTIME_LIBRARY_FILENAME"]} initialized!")
        return tox_lib

    @with_mutex("mutex")
    def _extract_public_key(self) -> str:
        public_address_buffer = ctypes.create_string_buffer(38)
        self._tox_lib.tox_self_get_address(self._tox_instance, public_address_buffer)
        return public_address_buffer.raw.hex().upper()

    @with_mutex("io_mutex")
    def _save_profile_file(self) -> None:
        self._logger.io(f"Saving tox profile file: {self._profile_file_path}")
        if not self._tox_instance:
            raise RuntimeError("Tox instance not initialized")
        profile_file_size = self._tox_lib.tox_get_savedata_size(self._tox_instance)
        if profile_file_size == 0:
            raise RuntimeError("Failed to retrieve profile data size (size is 0)")
        profile_buffer = (ctypes.c_uint8 * profile_file_size)()
        self._tox_lib.tox_get_savedata(self._tox_instance, profile_buffer)
        try:
            with open(self._profile_file_path, "wb") as f:
                f.write(bytes(profile_buffer))
            self._logger.info(f"Profile successfully saved to file: {self._profile_file_path}")
        except Exception as e:
            self._logger.exception(f"Exception while saving profile file: {e}")
            raise ToxIOException from e

    @with_mutex("io_mutex")
    def _load_profile_file(self, options) -> None:
        self._logger.io(f"Loading tox profile file: {self._profile_file_path}")
        try:
            with open(self._profile_file_path, "rb") as f:
                profile_file_data = f.read()
                if len(profile_file_data) == 0:
                    raise ToxIOException(f"The tox profile file: {self._profile_file_path} is empty")
                profile_file_data_buffer = (ctypes.c_char * len(profile_file_data)).from_buffer_copy(profile_file_data)

                self._logger.debug("Binding saved profile file data to boot options")
                self._tox_lib.tox_options_set_savedata_type(options, _MODULE_CONSTS["SAVEDATA_TYPE_SAVE"])
                self._tox_lib.tox_options_set_savedata_data(options, profile_file_data_buffer, len(profile_file_data))
                self._logger.info(f"Profile data from: {self._profile_file_path} has been successfully added to the load options")
        except Exception as e:
            self._logger.exception(f"Exception while writing profile file: {e}")
            raise ToxIOException from e

    @with_mutex("mutex")
    def _create_new_instance(self) -> None:
        options = self._tox_lib.tox_options_new(None)
        if not options:
            raise ToxCCoreException("Failed to create Tox Options")

        is_profile_file_exists: bool = os.path.exists(self._profile_file_path)
        if is_profile_file_exists:
            self._load_profile_file(options)
        else:
            self._logger.warning(f"Tox profile file does not exists: {self._profile_file_path}, creating new profile from private key")
            private_key_bytes = bytes.fromhex(self._config.private_key)
            private_key_length = len(private_key_bytes)
            private_key_c_array = (ctypes.c_char * private_key_length)(*private_key_bytes)
            private_key_c_array_ptr = ctypes.cast(private_key_c_array, ctypes.POINTER(ctypes.c_char))
            self._logger.note("Binding the raw private key to boot options")
            self._tox_lib.tox_options_set_savedata_type(options, _MODULE_CONSTS["SAVEDATA_TYPE_SECRET_KEY"])
            self._tox_lib.tox_options_set_savedata_data(options, private_key_c_array_ptr, ctypes.c_size_t(private_key_length))
            self._logger.info(f"Generated from private key profile file data has been successfully added to the Tox load options")

        tox_instance_err = ctypes.c_int(0)
        self._tox_instance = self._tox_lib.tox_new(options, ctypes.byref(tox_instance_err))
        if not self._tox_instance:
            raise ToxCCoreException(f"Failed to create Tox instance. C-Core Error Code: {tox_instance_err.value}")
        if not is_profile_file_exists:
            self._logger.note("The Tox instance has been launched directly from private key")
            self._save_profile_file()

        self._logger.debug("Registering callbacks...")
        self._on_incoming_message_func = self._friend_message_cb_prototype(self._on_incoming_message)
        self._tox_lib.tox_callback_friend_message(self._tox_instance, self._on_incoming_message_func)
        self._on_friend_request_func = self._friend_request_cb_prototype(self._on_friend_request)
        self._tox_lib.tox_callback_friend_request(self._tox_instance, self._on_friend_request_func)

    def _on_incoming_message(self, tox_instance, friend_number, message_type, message_ptr, length, user_data) -> None:
        try:
            text = ctypes.string_at(message_ptr, length).decode('utf-8')
            self._logger.info(f"Incoming message length: {length}, from: {friend_number}, text: {text}")
            self._output_queue.put(InternalQueuedItem(content={"text": text, "message_type": message_type, "from": friend_number},
                                                     main_type="incoming"))
        except Exception as e:
            self._logger.exception(f"Exception while processing incoming message callback: {e}")

    def _on_friend_request(self, tox_instance, public_key_ptr, message_ptr, length, user_data) -> None:
        main_type = "incoming_friend_request"
        raw_pk = ctypes.string_at(public_key_ptr, 32)
        pk_hex = raw_pk.hex().upper()
        request_message = ctypes.string_at(message_ptr, length).decode('utf-8', errors='replace')
        self._logger.info(f"Received friend request from TOX ID (PK): {pk_hex}. Message: {request_message}")

        if not self._config.accept_invites:
            self._logger.info(f"Successfully ignored friend request by config!")
            sub_type = "not_allowed"
        else:
            err = ctypes.c_int(0)
            friend_number = self._tox_lib.tox_friend_add_norequest(self._tox_instance, raw_pk, ctypes.byref(err))
            if friend_number == _MODULE_CONSTS["UINT32_MAX"] or err.value != 0:
                self._logger.error(f"Failed to accept friend request from {pk_hex}. C-Core Error: {err.value}")
                sub_type = "failed"
            else:
                sub_type = "accepted"
                self._logger.info(f"Successfully accepted friend request! Assigned friend_number: {friend_number}")
                try:
                    self._save_profile_file()
                except Exception as save_err:
                    self._logger.error(f"Failed to auto-save profile after accepting friend request: {save_err}")
        self._output_queue.put(InternalQueuedItem(
                content={"public_key": pk_hex, "message": request_message},
                main_type=main_type,
                sub_type=sub_type
        ))

    def run(self) -> None:
        self._logger.debug("Bootstrapping client thread...")
        #with self._mutex:
        super().run()
        self._logger.io(
            f"Connecting to a DHT node IP: {self._config.bootstrap_ip}, port {self._config.bootstrap_port}, public key: {self._config.bootstrap_key}")
        bootstrap_success = self._tox_lib.tox_bootstrap(self._tox_instance, self._config.bootstrap_ip.encode('utf-8'),
                                                        self._config.bootstrap_port,
                                                        bytes.fromhex(self._config.bootstrap_key), None)
        if not bootstrap_success:
            self._logger.critical("Bootstrap failed...")
            self._state = ThreadState.ERROR_DOWN
            return

        if self._config.instance_config.interval is None:
            sleep_interval = self._tox_lib.tox_iteration_interval(self._tox_instance) / 1000.0
        else:
            sleep_interval = self._config.instance_config.interval
        self._logger.note(f"Tox client sleep interval: {sleep_interval} sec")

        connected_flag: bool = False
        while not self._stop_signal.is_set():
            self._tox_lib.tox_iterate(self._tox_instance, None)
            status = self._tox_lib.tox_self_get_connection_status(self._tox_instance)
            if status > 0 and not connected_flag:
                self._logger.info(f"Successfully connected to the Tox network! Current status: {status}")
                connected_flag = True
            elif status == 0 and connected_flag:
                self._logger.error("Tox network connection lost")
                connected_flag = False
            for command in self._input_queue.get_batch(max_count=12):
                self._handle_command(command)
            time.sleep(sleep_interval)

    @with_mutex("mutex")
    def get_friend_list(self) -> List[ToxInterlocutor]:
        if not self._tox_instance:
            return []

        friend_list_size = self._tox_lib.tox_self_get_friend_list_size(self._tox_instance)
        if friend_list_size == 0:
            self._logger.attention("Tox friend list is empty")
            return []

        friend_list_array = (ctypes.c_uint32 * friend_list_size)()
        self._tox_lib.tox_self_get_friend_list(self._tox_instance, friend_list_array)
        friends: List[ToxInterlocutor] = list()
        for friend_number in friend_list_array:
            pk_buffer = ctypes.create_string_buffer(_MODULE_CONSTS["PUBLIC_KEY_SIZE"])
            err = ctypes.c_int(0)
            success = self._tox_lib.tox_friend_get_public_key(
                self._tox_instance,
                friend_number,
                pk_buffer,
                ctypes.byref(err)
            )
            if success:
                status_err = ctypes.c_int(0)
                connection_status = self._tox_lib.tox_friend_get_connection_status(
                    self._tox_instance,
                    friend_number,
                    ctypes.byref(status_err)
                )
                pk_hex = pk_buffer.raw.hex().upper()
                connection_status_str = _MODULE_CONSTS["CONNECTION_STATUSES"].get(connection_status, "Unknown")
                friends.append(ToxInterlocutor(pk_hex, connection_status_str, self._logger.strftime_now()))
            else:
                self._logger.error(f"Failed to get public key for friend #{friend_number}. Error: {err.value}")
                return []
            for friend in friends:
                try:
                    fetch_equals(ToxInterlocutor, field="public_key", value=friend.public_key)
                except TypeError:
                    friend.create_entry()
        return friends

    def _send_message(self, friend_number: str, message: str) -> int:
        self._logger.debug(f"Trying send message Text: {message}, To: {friend_number}")
        friend_pk_bytes = bytes.fromhex(friend_number[:64])
        friend_err = ctypes.c_int(0)
        friend_number = self._tox_lib.tox_friend_add_norequest(self._tox_instance, friend_pk_bytes, ctypes.byref(friend_err))
        self._logger.debug(f"The interlocutor is registered under number: {friend_number}")

        f_err = ctypes.c_int(0)
        friend_status = self._tox_lib.tox_friend_get_connection_status(self._tox_instance, friend_number, ctypes.byref(f_err))
        if friend_status > 0:
            self._logger.note("The interlocutor person is online, sending message")
            message_bytes = message.encode('utf-8')
            message_len = len(message_bytes)
            c_array = (ctypes.c_char * message_len)(*message_bytes)
            c_ptr = ctypes.cast(c_array, ctypes.POINTER(ctypes.c_char))
            err = ctypes.c_int(0)
            msg_id = self._tox_lib.tox_friend_send_message(
                self._tox_instance,
                friend_number,
                _MODULE_CONSTS["TEXT_MESSAGE_TYPE_DEFAULT"],
                c_ptr,
                ctypes.c_size_t(message_len),
                ctypes.byref(err)
            )
            if msg_id == _MODULE_CONSTS["UINT32_MAX"] or err.value != 0:
                self._logger.attention(f"Failed to send the message. C-Core error code: {err.value}")
                if err.value == _MODULE_CONSTS["FRIEND_NOT_CONNECTED_ONLINE_ERROR"]:
                    self._logger.error("The interlocutor is currently offline. Message cannot be delivered")
                    raise ToxInterlocutorNotOnlineException()
                else:
                    raise ToxCCoreException(str(err.value))
            else:
                self._logger.info(f"Message sent, message id: {msg_id}")
                return msg_id

    def _handle_command(self, item: InternalQueuedItem) -> None:
        if item.main_type != "command":
            self._logger.warning(f"Skipping not command item: {item.to_json()}")
            return
        match item.sub_type:
            case "send_message":
                content_kwargs = item.content.copy()
                try:
                    content_kwargs["message_id"] = self._send_message(**item.content)
                except ToxInterlocutorNotOnlineException:
                    content_kwargs["status"] = "Tox interlocutor not online"
                except ToxCCoreException as tcce:
                    content_kwargs["status"] = f"Tox core exception {tcce}"
                except Exception as e:
                    content_kwargs["status"] = f"Other sending exeption: {e}"
                else:
                    content_kwargs["status"] = "Success"
                self._output_queue.put(InternalQueuedItem(content=content_kwargs,
                                                          main_type="command_status",
                                                          sub_type="send_message"))
            case "stop":
                self.finalize()

    @with_mutex("mutex")
    @with_mutex("io_mutex")
    def finalize(self):
        super().finalize()

    def send_message_command(self, friend_number: int, message: str) -> None:
        self._input_queue.put(InternalQueuedItem(
                content={"friend_number": friend_number, "message": message},
                main_type="command",
                sub_type="send_message",
        ))
        self._logger.notify("send_message command accepted")

    def stop_command(self) -> None:
        self._input_queue.put(InternalQueuedItem(
                content={},
                main_type="command",
                sub_type="stop"
        ))
        self._logger.notify("stop command accepted")
