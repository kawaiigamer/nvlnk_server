import asyncio
import os
import random
import struct
from typing import Optional, Generator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import Response


class AesGCM:
    def __init__(self,  key_str: str, iv_length: int, tag: str):
        key = bytes.fromhex(key_str)
        if len(key) != 32:
            raise ValueError("AES-256 key length must be 32 bytes!")
        self._crypter = AESGCM(key)
        self._iv_length = iv_length
        self._aes_payload_length: int = iv_length + len(tag)
        self._tag_bytes: bytes = tag.encode()

    @property
    def additional_payload_length(self):
        return self._aes_payload_length

    def encrypt(self, data: bytes) -> bytes:
        return self._crypter.encrypt(os.urandom(self._iv_length), data, self._tag_bytes)

    def decrypt(self, data: bytes) -> bytes:
        return self._crypter.decrypt(data[:self._iv_length], data[self._iv_length+len(self._tag_bytes):], data[self._iv_length:self._iv_length+len(self._tag_bytes)])


class WavAudio:
    def __init__(self, channels: int, channel_bit_depth: int, samples_rate: int):
        self.channels = channels
        self.channel_bit_depth = channel_bit_depth
        self.samples_rate = samples_rate
        self.sample_length = self.channels * int(self.channel_bit_depth // 8) * self.samples_rate

    def create_wav_header(self) -> bytes:
        block_align = self.channels * (self.channel_bit_depth // 8)
        byte_rate = self.samples_rate * block_align
        riff_chunk_size = 36
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',  # ChunkID
            riff_chunk_size,  # ChunkSize
            b'WAVE',  # Format
            b'fmt ',  # Subchunk1ID
            16,  # Subchunk1Size (16 for PCM)
            1,  # AudioFormat (1 for uncompressed PCM)
            self.channels,  # NumChannels
            self.samples_rate,  # SampleRate
            byte_rate,  # ByteRate
            block_align,  # BlockAlign
            self.channel_bit_depth,  # BitsPerSample
            b'data',  # Subchunk2ID
            0  # Subchunk2Size 0 if the data size is unknown or streaming
        )
        return header

    def create_empty_sample(self) -> bytes:
        return bytes(self.sample_length)

    def create_random_sample(self) -> bytes:
        return random.randbytes(self.sample_length)


class AsyncRandomAudioStream:
    def __init__(self, wav: WavAudio, crypter: Optional[AesGCM]):
        self.wav = wav
        self.samples_delay = 1 / self.wav.samples_rate
        if crypter:
            self.sample_body_length = self.wav.sample_length - crypter.additional_payload_length
            if self.sample_body_length <= 0:
                raise ValueError(f"Sample body length: {self.sample_body_length} must be bigger then: {crypter.additional_payload_length}")
            self.sample_gen = self.__random_aes_crypted_samples_gen(crypter)
        else:
            self.sample_gen = self.__random_samples_gen()

    def __random_aes_crypted_samples_gen(self, crypter: AesGCM) -> Generator[bytes, None, None]:
        while True:
            yield crypter.encrypt(random.randbytes(self.sample_body_length))

    def __random_samples_gen(self) -> Generator[bytes, None, None]:
        while True:
            yield self.wav.create_random_sample()

    async def __stream_generator(self):
        yield self.wav.create_wav_header()
        while True:
            yield next(self.sample_gen)
            await asyncio.sleep(self.samples_delay)

    def __sync_generator_wrapper(self):
        loop = asyncio.new_event_loop()
        stream_gen = self.__stream_generator()
        try:
            while True:
                try:
                    chunk = loop.run_until_complete(stream_gen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    def start(self) -> Response:
        return Response(self.__sync_generator_wrapper(), mimetype='audio/wav')
