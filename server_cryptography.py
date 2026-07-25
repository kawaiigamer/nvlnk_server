import os
from typing import Union, Dict, Self, Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding


class AESCrypterBase:
    def __init__(self, key_str: str, iv_length: int, text: str = "", **kwargs):
        self.key = bytes.fromhex(key_str)
        if len(self.key) != 32:
            raise ValueError("AES-256 key length must be 32 bytes!")
        self.iv_length = iv_length
        self.text = text

    @property
    def additional_payload_length(self) -> int:
        return 0

    def encrypt(self, data: Union[bytes, str]) -> bytes:
        raise NotImplemented(f"Not implemented in {self.__class__.__name__} class")

    def decrypt(self, data: bytes) -> str:
        raise NotImplemented(f"Not implemented in {self.__class__.__name__} class")

    def to_json(self) -> Dict[str, Any]:
        return {"class": self.__class__.__name__, "key": self.key.hex().upper(), "iv_length": self.iv_length, "text_for_crypt": self.text, "additional_payload_length": self.additional_payload_length}

    @staticmethod
    def from_config(config: Dict[str, Union[str, int]]) -> Self:
        mode = config.get("mode", "CBC")
        if mode == "GCM":
            return AESCrypterGCM(**config)
        elif mode == "CBC":
            return AESCrypterCBC(**config)
        else:
            raise ValueError(f"Selected AES256 mode is not supported: {mode}")


class AESCrypterGCM(AESCrypterBase):
    def __init__(self, tag: str = "", **kwargs):
        super().__init__(**kwargs)
        self._crypter = AESGCM(self.key)
        self._aes_payload_length: int = self.iv_length + len(tag)
        self._tag_bytes: bytes = tag.encode()

    @property
    def additional_payload_length(self) -> int:
        return self._aes_payload_length

    def encrypt(self, data: Union[bytes, str]) -> bytes:
        return self._crypter.encrypt(os.urandom(self.iv_length), data.encode() if isinstance(data, str) else data, self._tag_bytes)

    def decrypt(self, data: bytes) -> str:
        return self._crypter.decrypt(data[:self.iv_length], data[self.iv_length + len(self._tag_bytes):], data[self.iv_length:self.iv_length + len(self._tag_bytes)]).decode('utf-8')

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "tag": self._tag_bytes.hex().upper()}


class AESCrypterCBC(AESCrypterBase):

    @property
    def additional_payload_length(self) -> int:
        return self.iv_length

    def encrypt(self, data: Union[bytes, str]) -> bytes:
        if isinstance(data, str):
            data = data.encode('utf-8')
        iv = os.urandom(self.iv_length)
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(data) + padder.finalize()
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        encrypted_bytes = encryptor.update(padded_data) + encryptor.finalize()
        return encrypted_bytes + iv

    def decrypt(self, data: bytes) -> str:
        iv = data[-self.iv_length:]
        ciphertext = data[:len(data)-self.iv_length]
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv))
        decryptor = cipher.encryptor() if False else cipher.decryptor()
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plain_text_bytes = unpadder.update(padded_data) + unpadder.finalize()
        return plain_text_bytes.decode('utf-8')
