import threading
import queue
import time
import tox
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from server_logging import EndpointLogger

_PRIVATE_TOX_PATH = "./tox"


def _decrypt_data(encrypted_bytes: bytes, password: str) -> bytes:
    """
    Пример расшифровки.
    Здесь нужно использовать тот же формат, что и при шифровании:
    encrypted = nonce + ciphertext + tag (или как вы сохраняли).
    Это лишь шаблон — адаптируйте под свой формат.
    """
    # Для примера предполагаем, что первые 12 байт — nonce, остальное — ciphertext+tag
    nonce = encrypted_bytes[:12]
    ciphertext = encrypted_bytes[12:]

    # Из пароля делаем 256-битный ключ (в реальности используйте KDF, например PBKDF2)
    import hashlib
    key = hashlib.sha256(password.encode("utf-8")).digest()

    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    return decrypted


class ToxClientThread(threading.Thread):
    def __init__(self, logger: EndpointLogger, settings_name: str, settings_file_password: str):
        super().__init__()
        self._logger = logger
        self._settings_file_path = settings_name
        self._settings_file_password = settings_file_password
        self._running = False
        self._lock = threading.Lock()
        self.cmd_queue = queue.Queue()
        self.tox_client = None

    def is_running(self) -> bool:
        return self._running

    def run(self):
        self._logger.debug("Starting client tox thread")
        savedata_path = f"{_PRIVATE_TOX_PATH}/{self._settings_file_path}"

        try:
            with open(savedata_path, "rb") as f:
                encrypted_bytes = f.read()

            # Если файл зашифрован — расшифровываем, иначе используем как есть.
            # Логика определения "зашифрован/нет" зависит от вашего формата.
            # Например, можно проверять префикс или хранить отдельный флаг.
            decrypted_bytes = _decrypt_data(encrypted_bytes, self._settings_file_password)
        except FileNotFoundError:
            self._logger.error(f"Tox saved file not found: {savedata_path}")
            return
        except Exception as e:
            self._logger.exception(f"Failed to decrypt Tox saved file: {e}")
            return

        self.tox_client = tox.Tox(
            savedata_data=decrypted_bytes,
            savedata_type=tox.SAVEDATA_TYPE_TOX_SAVE,
        )

        # Bootstrap
        # self.tox_client.bootstrap("bootstrap.tox.chat", 33445, "ПУБЛИЧНЫЙ_КЛЮЧ_УЗЛА")

        # Регистрация коллбэков
        # self.tox_client.callback_friend_message(self.on_friend_message)

        self._running = True
        self._logger.info("Tox client is running in the background thread...")

        while self._running:
            self.tox_client.iterate()
            try:
                while not self.cmd_queue.empty():
                    cmd_type, data = self.cmd_queue.get_nowait()
                    self._handle_command(cmd_type, data)
                    self.cmd_queue.task_done()
            except queue.Empty:
                pass
            time.sleep(self.tox_client.iteration_interval() / 1000.0)

    def _handle_command(self, cmd_type, data):
        if cmd_type == "send_msg":
            friend_number, message = data
            try:
                self.tox_client.friend_send_message(friend_number, message.encode("utf-8"))
                self._logger.info(f"Message Text: {message} sent to {friend_number}")
            except Exception as e:
                self._logger.exception(f"Message sending error, Text: {message} sent to {friend_number}, {e}")
        elif cmd_type == "stop":
            self._running = False
            self._logger.info("Tox client stopped...")

    def send_message_safely(self, friend_number, message):
        self._logger.debug("send_msg command received")
        self.cmd_queue.put(("send_msg", (friend_number, message)))

    def stop_safely(self):
        self._logger.debug("Stop command received")
        self.cmd_queue.put(("stop", None))