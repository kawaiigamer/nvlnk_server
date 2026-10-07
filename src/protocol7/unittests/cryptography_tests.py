import os
from typing import Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.protocol7.cryptography import AES256CrypterGCM, AES256CrypterCBC
from src.protocol7.unittests.unittest_base import UnitTestsBase


class CryptographyTests(UnitTestsBase):

    def setUp(self):
        super().setUp()
        self.plaintext: str = "Secret utf-8 data!Таємні дані у форматі UTF-8!秘密のUTF-8データ！"

    def __test_gcm_utf8(self, iv_length: int, gcm_sequence: str = "NONCE,CIPHERTEXT,TAG"):
        key = AESGCM.generate_key(bit_length=256)
        crypter = AES256CrypterGCM(**{"key": key, "iv_length": iv_length, "gcm_sequence": gcm_sequence})
        encrypted = crypter.encrypt(self.plaintext)
        decrypted = crypter.decrypt(encrypted)
        self.assertEqual(self.plaintext, decrypted)

    def __test_cbc_utf8(self, hmac_key: Union[bytes, str], gcm_sequence: str = "IV,CIPHERTEXT,HMAC"):
        key = AESGCM.generate_key(bit_length=256)
        crypter = AES256CrypterCBC(**{"key": key, "hmac_key": hmac_key, "cbc_sequence": gcm_sequence})
        encrypted = crypter.encrypt(self.plaintext)
        decrypted = crypter.decrypt(encrypted)
        self.assertEqual(self.plaintext, decrypted)

    def test_gcm(self):
        self.__test_gcm_utf8(13, "NONCE,CIPHERTEXT,TAG")
        self.__test_gcm_utf8(14, "NONCE,TAG,CIPHERTEXT")
        self.__test_gcm_utf8(15, "CIPHERTEXT,NONCE,TAG")
        self.__test_gcm_utf8(16, "TAG,NONCE,CIPHERTEXT")

    def test_cbc(self):
        self.__test_cbc_utf8(os.urandom(150), "IV,CIPHERTEXT,HMAC")
        self.__test_cbc_utf8(os.urandom(42), "CIPHERTEXT,IV,HMAC")
        self.__test_cbc_utf8(os.urandom(33), "HMAC,CIPHERTEXT,IV")
        self.__test_cbc_utf8(os.urandom(33), "HMAC,IV,CIPHERTEXT")


if __name__ == '__main__':
    CryptographyTests().run()
