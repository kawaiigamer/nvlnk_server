import asyncio
import os
import random
import struct
from typing import Optional, Generator

import numpy as np
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
        self.sample_length = self.channels * int(self.channel_bit_depth // 8)
        self.frame_length = self.sample_length * self.samples_rate

    def create_wav_header(self) -> bytes:
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
            self.frame_length,  # ByteRate
            self.sample_length,  # BlockAlign
            self.channel_bit_depth,  # BitsPerSample
            b'data',  # Subchunk2ID
            0  # Subchunk2Size 0 if the data size is unknown or streaming
        )
        return header

    def create_empty_frame(self) -> bytes:
        return bytes(self.frame_length)

    def create_random_frame(self) -> bytes:
        return random.randbytes(self.frame_length)

    def to_json(self):
        return {"channels": self.channels, "channel_bit_depth": self.channel_bit_depth, "samples_rate": self.samples_rate, "sample_length": self.sample_length, "frame_length": self.frame_length}


class WavAudioFSK2(WavAudio):
    def __init__(self, samples_per_full_vs_symbol: int, samples_per_value_symbol: int, **kwargs):
        super().__init__(**kwargs)
        self.samples_per_full_vs_symbol = samples_per_full_vs_symbol
        self.samples_per_value_symbol = samples_per_value_symbol
        self.samples_per_sync_symbol = samples_per_full_vs_symbol - samples_per_value_symbol
        vsps, vsps_mod = divmod(self.samples_rate, samples_per_full_vs_symbol)
        if vsps_mod != 0:
            raise ValueError(f"Divmod of sample rate on sampels per valued symbol must be integer({self.samples_rate}/{samples_per_full_vs_symbol}={vsps}+mod({vsps_mod}))")
        self.valued_symbols_per_sec = vsps
        self.v_sym_0 = np.int16(-32768)  # b'0x8000'
        self.v_sym_1 = np.int16(32767)  # b'0x7FFF'
        self.s_sym = np.int16(0)  # b'0x0000'
        self.v_sym_seq_length = self.samples_per_value_symbol * self.channels
        self.s_sym_seq_length = self.samples_per_sync_symbol * self.channels

    def create_random_bits(self, length: int) -> np.array:
        return np.random.randint(0, 2, size=length)

    def bits_to_str(self, bits: np.array) -> str:
        return "".join(bits.astype(str))

    def create_fsk_frame(self, bits: np.array) -> bytes:  # TODO: Optimize
        frame = np.zeros(self.frame_length//2, dtype=np.int16)
        counter = 0
        for b in bits:
            if b:
                sym = self.v_sym_1
            else:
                sym = self.v_sym_0
            for i in range(self.v_sym_seq_length):
                    frame[counter] = sym
                    counter += 1
            for i in range(self.s_sym_seq_length):
                frame[counter] = self.s_sym
                counter += 1
        return frame.tobytes()

    def to_json(self):
        j = super().to_json()
        j.update({"samples_per_full_vs_symbol": self.samples_per_full_vs_symbol, "samples_per_value_symbol": self.samples_per_value_symbol,
                  "samples_per_sync_symbol": self.samples_per_sync_symbol, "valued_symbols_per_sec": self.valued_symbols_per_sec,
                  "v_sym_0": self.v_sym_0, "v_sym_1": self.v_sym_1, "s_sym": self.s_sym, "v_sym_seq_length": self.v_sym_seq_length, "s_sym_seq_length": self.s_sym_seq_length})
        return j


class AsyncRandomAudioStream:
    def __init__(self, wav: WavAudio, crypter: Optional[AesGCM]):
        self.wav = wav
        self.frames_delay = 1
        if crypter:
            self.frame_body_length = self.wav.frame_length - crypter.additional_payload_length
            if self.frame_body_length <= 0:
                raise ValueError(f"Sample body length: {self.frame_body_length} must be bigger then: {crypter.additional_payload_length}")
            self.sample_gen = self.__random_aes_crypted_frames_gen(crypter)
        else:
            if isinstance(self.wav, WavAudioFSK2):
                self.sample_gen = self.__random_fsk_frames_gen()
            else:
                self.sample_gen = self.__random_frames_gen()

    def __random_aes_crypted_frames_gen(self, crypter: AesGCM) -> Generator[bytes, None, None]:
        while True:
            yield crypter.encrypt(random.randbytes(self.frame_body_length))

    def __random_frames_gen(self) -> Generator[bytes, None, None]:
        while True:
            yield self.wav.create_random_frame()

    def __random_fsk_frames_gen(self) -> Generator[bytes, None, None]:
        while True:
            bits = self.wav.create_random_bits(self.wav.valued_symbols_per_sec)
            yield self.wav.create_fsk_frame(bits)

    async def __stream_generator(self):
        yield self.wav.create_wav_header()
        while True:
            yield next(self.sample_gen)
            await asyncio.sleep(self.frames_delay)

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
