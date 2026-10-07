import hashlib
import os
import hmac
from enum import unique, Enum, auto
from typing import Union, Dict, Self, Any, Tuple, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding


class AESCrypterBase:
    def __init__(self, key: Union[str, bytes], iv_length: int = 12, **kwargs):
        self._key = bytes.fromhex(key) if isinstance(key, str) else key
        if len(self._key) != 32:
            raise ValueError("AES-256 key length must be 32 bytes!")
        self._iv_length: int = iv_length

    @property
    def additional_payload_length(self) -> int:
        raise NotImplementedError(f"Not implemented in {self.__class__.__name__} class")

    def encrypt(self, data: Union[bytes, str]) -> bytes:
        raise NotImplementedError(f"Not implemented in {self.__class__.__name__} class")

    def decrypt(self, data: bytes) -> str:
        raise NotImplementedError(f"Not implemented in {self.__class__.__name__} class")

    def to_json(self) -> Dict[str, Any]:
        return {"class": self.__class__.__name__, "key": self._key.hex().upper(), "iv_length": self._iv_length, "additional_payload_length": self.additional_payload_length}

    @staticmethod
    def from_config(config: Dict[str, Union[str, int]]) -> Self:
        mode = config.get("mode", "CBC")
        if mode == "GCM":
            return AES256CrypterGCM(**config)
        elif mode == "CBC":
            return AES256CrypterCBC(**config)
        else:
            raise ValueError(f"Selected AES256 mode is not supported: {mode}")


@unique
class GCMPart(Enum):
    TAG = 0
    CIPHERTEXT = 1
    NONCE = 2


class AES256CrypterGCM(AESCrypterBase):
    _TAG_SIZE = 16

    def __init__(self, gcm_sequence: Union[Tuple[GCMPart, GCMPart, GCMPart], str] = (GCMPart.NONCE, GCMPart.CIPHERTEXT, GCMPart.TAG), **kwargs):
        super().__init__(**kwargs)
        self.gcm_sequence = tuple(GCMPart[sm] for sm in gcm_sequence.split(",")) if isinstance(gcm_sequence, str) else gcm_sequence
        if self._iv_length < 12 or self._iv_length > 16:
            raise ValueError(f"Nonce length must be from 12 to 16 bytes for GCM mode, but not {self._iv_length}")
        self._crypter = AESGCM(self._key)
        self._aes_payload_length: int = self._iv_length + self._TAG_SIZE

    @property
    def additional_payload_length(self) -> int:
        return self._aes_payload_length

    def _build(self, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
        result: bytes = b""
        for part in self.gcm_sequence:
            match part:
                case GCMPart.TAG:
                    result += tag
                case GCMPart.CIPHERTEXT:
                    result += ciphertext
                case GCMPart.NONCE:
                    result += nonce
        return result

    def _split(self, data: bytes) -> Tuple[bytes, bytes, bytes]:
        tag = b""
        ciphertext = b""
        nonce = b""
        ciphertext_len = len(data) - self._iv_length - self._TAG_SIZE
        if ciphertext_len <= 0:
            raise ValueError("Data is too short to contain nonce, tag and ciphertext")
        offset: int = 0
        for part in self.gcm_sequence:
            match part:
                case GCMPart.TAG:
                    tag = data[offset:offset + self._TAG_SIZE]
                    offset += self._TAG_SIZE
                case GCMPart.CIPHERTEXT:
                    ciphertext = data[offset:offset + ciphertext_len]
                    offset += ciphertext_len
                case GCMPart.NONCE:
                    nonce = data[offset:offset + self._iv_length]
                    offset += self._iv_length
        if len(tag) != self._TAG_SIZE:
            raise ValueError("Invalid GCM tag length")
        if len(nonce) != self._iv_length:
            raise ValueError("Invalid GCM nonce length")
        if not ciphertext:
            raise ValueError("Empty GCM ciphertext")
        return tag, ciphertext, nonce

    def encrypt(self, data: Union[bytes, str]) -> bytes:
        nonce: bytes = os.urandom(self._iv_length)
        plain_data: bytes = data.encode() if isinstance(data, str) else data
        encrypted_with_tag: bytes = self._crypter.encrypt(nonce, plain_data, None)
        ciphertext: bytes = encrypted_with_tag[:-self._TAG_SIZE]
        tag: bytes = encrypted_with_tag[-self._TAG_SIZE:]
        return self._build(nonce, ciphertext, tag)

    def decrypt(self, data: Union[bytes, str]) -> str:
        tag, ciphertext, nonce = self._split(data.encode() if isinstance(data, str) else data)
        return self._crypter.decrypt(nonce, ciphertext + tag, None).decode()

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "gcm_sequence": ",".join([sm.name for sm in self.gcm_sequence])}


@unique
class CBCPart(Enum):
    IV = 0
    CIPHERTEXT = 1
    HMAC = 2


class AES256CrypterCBC(AESCrypterBase):
    _IV_SIZE = 16
    _HMAC_SIZE = 32

    def __init__(self, hmac_key: Union[str, bytes], cbc_sequence: Union[Tuple[CBCPart, CBCPart, CBCPart], str] = (CBCPart.IV, CBCPart.CIPHERTEXT, CBCPart.HMAC), **kwargs):
        super().__init__(**kwargs)
        self.cbc_sequence = tuple(CBCPart[sm] for sm in cbc_sequence.split(",")) if isinstance(cbc_sequence, str) else cbc_sequence
        self._hmac_key: bytes = hmac_key.encode() if isinstance(hmac_key, str) else hmac_key
        self._aes_payload_length = self._IV_SIZE + self._HMAC_SIZE
        self._iv_length = self._IV_SIZE

    @property
    def additional_payload_length(self) -> int:
        return self._aes_payload_length

    def _build(self, iv: bytes, ciphertext: bytes, hmac: bytes) -> bytes:
        result: bytes = b""
        for part in self.cbc_sequence:
            match part:
                case CBCPart.IV:
                    result += iv
                case CBCPart.CIPHERTEXT:
                    result += ciphertext
                case CBCPart.HMAC:
                    result += hmac
        return result

    def _split(self, data: bytes) -> Tuple[bytes, bytes, bytes]:
        iv = b""
        ciphertext = b""
        hmac_val = b""
        ciphertext_len = len(data) - self._iv_length - self._HMAC_SIZE
        if ciphertext_len <= 0:
            raise ValueError("Data is too short to contain IV, HMAC and ciphertext")
        if ciphertext_len % 16 != 0:
            raise ValueError("Invalid ciphertext length (not block aligned)")
        offset: int = 0
        for part in self.cbc_sequence:
            match part:
                case CBCPart.IV:
                    iv = data[offset: offset + self._iv_length]
                    offset += self._iv_length
                case CBCPart.CIPHERTEXT:
                    ciphertext = data[offset: offset + ciphertext_len]
                    offset += ciphertext_len
                case CBCPart.HMAC:
                    hmac_val = data[offset: offset + self._HMAC_SIZE]
                    offset += self._HMAC_SIZE
        if len(iv) != self._iv_length:
            raise ValueError("Invalid CBC IV length")
        if len(hmac_val) != self._HMAC_SIZE:
            raise ValueError("Invalid HMAC length")
        if not ciphertext:
            raise ValueError("Empty CBC ciphertext")
        return iv, ciphertext, hmac_val

    def encrypt(self, data: Union[bytes, str]) -> bytes:
        iv = os.urandom(self._iv_length)
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(data.encode('utf-8') if isinstance(data, str) else data) + padder.finalize()
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        encrypted_bytes = encryptor.update(padded_data) + encryptor.finalize()
        hmac_sha256: bytes = hmac.digest(self._hmac_key, encrypted_bytes + iv, hashlib.sha256)
        return self._build(iv, encrypted_bytes, hmac_sha256)

    def decrypt(self, data: Union[bytes, str]) -> str:
        iv, ciphertext, hmac_val = self._split(bytes.fromhex(data) if isinstance(data, str) else data)
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        decryptor =  cipher.decryptor()
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plain_text_bytes = unpadder.update(padded_data) + unpadder.finalize()
        return plain_text_bytes.decode()

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "hmac_key": self._hmac_key, "cbc_sequence": ",".join([sm.name for sm in self.cbc_sequence])}
