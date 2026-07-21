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
    def __init__(self, channels: int, channel_bit_depth: int, samples_rate: int, data_type: str = "int16"):
        self.channels = channels
        self.channel_bit_depth = channel_bit_depth
        self.samples_rate = samples_rate
        self.sample_length = self.channels * int(self.channel_bit_depth // 8)
        self.frame_length = self.sample_length * self.samples_rate
        try:
            self.data_type: np.dtype = np.dtype(data_type).type
        except TypeError:
            self.data_type: np.dtype = np.dtype("int16").type
        self.data_type_length: int = np.dtype(self.data_type).itemsize

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
        return {"channels": self.channels, "channel_bit_depth": self.channel_bit_depth, "samples_rate": self.samples_rate,
                "sample_length": self.sample_length, "frame_length": self.frame_length, "data_type": self.data_type, "data_type_length": self.data_type_length}


class WavAudioFSK2(WavAudio):
    def __init__(self, full_vs_symbol_samples_count: int, value_symbol_samples_count: int, **kwargs):
        super().__init__(**kwargs)
        self.full_vs_symbol_samples_count = full_vs_symbol_samples_count
        self.value_symbol_samples_count = value_symbol_samples_count
        self.sync_symbol_samples_count = full_vs_symbol_samples_count - value_symbol_samples_count
        ffsc, ffsc_mod = divmod(self.samples_rate, full_vs_symbol_samples_count)
        if ffsc_mod != 0:
            raise ValueError(f"Divmod of sample rate on sampels per valued symbol must be integer({self.samples_rate}/{full_vs_symbol_samples_count}={ffsc}+mod({ffsc_mod}))")
        self.frame_full_symbols_count = ffsc
        self.v_sym_0 = self.data_type(-32768)  # b'0x8000'
        self.v_sym_1 = self.data_type(32767)   # b'0x7FFF'
        self.s_sym = self.data_type(0)   # b'0x0000'
        self.v_sym_seq_length = self.value_symbol_samples_count * self.channels
        self.s_sym_seq_length = self.sync_symbol_samples_count * self.channels
        self.value_symbol_duration_sec = self.value_symbol_samples_count / self.samples_rate
        self.sync_symbol_duration_sec = self.sync_symbol_samples_count / self.samples_rate
        self.full_symbol_duration_sec = self.full_vs_symbol_samples_count / self.samples_rate

    def create_random_bits(self, bits_length: int) -> np.ndarray:
        return np.random.randint(0, 2, size=bits_length)

    def ndarray_bits_to_str(self, nparray_bits: np.ndarray) -> str:
        result = list("?" * len(nparray_bits))
        for i, b in enumerate(nparray_bits):
            if b:
                result[i] = '1'
            else:
                result[i] = '0'
        return "".join(result)

    def fsk_byte_frame_to_str(self, frame: bytes, add_sync_symbols: bool = False) -> str:
        return self.fsk_frame_to_str(np.frombuffer(frame, dtype=self.data_type), add_sync_symbols)

    def fsk_frame_to_str(self, frame: np.ndarray, add_sync_symbols: bool = False) -> str:
        if len(frame) != self.frame_length//self.data_type_length:
            raise ValueError(f"Target frame length({len(frame)}) not eq expected frame length({self.frame_length//self.data_type_length}) casted to data type({self.data_type})")
        result = list("?" * self.frame_full_symbols_count)
        if add_sync_symbols:
            result = result * 2
        counter = 0
        res_index = 0
        while counter < len(frame):
            if frame[counter] == self.v_sym_0:
                result[res_index] = '0'
                counter += self.v_sym_seq_length
                res_index += 1
            elif frame[counter] == self.v_sym_1:
                result[res_index] = '1'
                counter += self.v_sym_seq_length
                res_index += 1
            elif frame[counter] == self.s_sym:
                counter += self.s_sym_seq_length
                if add_sync_symbols:
                    result[res_index] = 'S'
                    res_index += 1
        return "".join(result)

    def create_fsk_frame(self, bits: np.ndarray) -> np.ndarray:  # TODO: Optimize
        frame: np.ndarray = np.zeros(self.frame_length//self.data_type_length, dtype=self.data_type)
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
        return frame

    def to_json(self):
        j = super().to_json()
        j.update({"full_vs_symbol_samples_count": self.full_vs_symbol_samples_count, "value_symbol_samples_count": self.value_symbol_samples_count,
                  "sync_symbol_samples_count": self.sync_symbol_samples_count, "frame_full_symbols_count": self.frame_full_symbols_count,
                  "v_sym_0": self.v_sym_0, "v_sym_1": self.v_sym_1, "s_sym": self.s_sym, "v_sym_seq_length": self.v_sym_seq_length, "s_sym_seq_length": self.s_sym_seq_length,
                  "value_symbol_duration_sec": self.value_symbol_duration_sec, "sync_symbol_duration_sec": self.sync_symbol_duration_sec, "full_symbol_duration_sec": self.full_symbol_duration_sec})
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
            bits: np.ndarray = self.wav.create_random_bits(self.wav.frame_full_symbols_count)
            fsk_frame: np.ndarray = self.wav.create_fsk_frame(bits)
            yield fsk_frame.tobytes()

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
