import asyncio
import itertools
import json
import math
import os
import random
import string
import struct
import io
import wave
from itertools import count
from typing import Optional, Generator, AsyncGenerator, Union, List, Iterable, Tuple, Dict, Self, Callable, Type

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from flask import Response


class AESBase:
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
        raise NotImplemented

    def decrypt(self, data: bytes) -> str:
        raise NotImplemented

    def to_json(self):
        return {"class": self.__class__.__name__, "key": self.key.hex().upper(), "iv_length": self.iv_length, "text_for_crypt": self.text, "additional_payload_length": self.additional_payload_length}

    @staticmethod
    def from_config(config: Dict[str, Union[str, int]]) -> Self:
        print(config)
        mode = config.get("mode", "CBC")
        if mode == "GCM":
            return AESGCM(**config)
        elif mode == "CBC":
            return AESCBC(**config)
        else:
            raise ValueError(f"Selected AES256 mode is not supported: {mode}")


class AESGCM(AESBase):
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

    def to_json(self):
        return {**super().to_json(), "tag": self._tag_bytes.hex().upper()}


class AESCBC(AESBase):

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


class WavAudio:
    _supported_data_types = ("int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float16", "float32", "float64")
    WAVE_FORMAT_PCM = 1
    WAVE_FORMAT_IEEE_FLOAT = 3

    def _int_div(self, x: int, y: int, x_name: str, y_name_: str) -> int:
        r, r_mod = divmod(x, y)
        if r_mod != 0:
            raise ValueError(f"Divmod of {x_name} on {y_name_} must be integer({x}/{y}={r}+mod({r_mod}))")
        return r

    def __init__(self, channels: int, channel_bit_depth: int, samples_rate: int, data_type: str = "int16", duration: int = 0, info_only: str = "false"):
        self.info_only = info_only.lower() == 'true'
        self.channels = channels
        self.channel_bit_depth = channel_bit_depth
        self.samples_rate = samples_rate
        self.sample_length = self.channels * int(self.channel_bit_depth // 8)
        self.frame_length = self.sample_length * self.samples_rate
        if data_type not in self._supported_data_types:
            raise ValueError(f"Selected data type: {data_type} is not supported!")
        try:
            self.data_type: Union[np.integer, np.floating] = np.dtype(data_type).type
        except TypeError:
            self.data_type: Union[np.integer, np.floating] = np.dtype("int16").type
        self.data_type_info = np.finfo(self.data_type) if data_type.startswith("f") else np.iinfo(self.data_type)
        self.data_type_length: int = np.dtype(self.data_type).itemsize
        self.frame_length_in_data_type = self._int_div(self.frame_length, self.data_type_length, "frame length", "data type length")
        self.duration = duration

    def create_wav_header(self, fixed_frames_count: int = 0) -> bytes:
        if fixed_frames_count:
            data_size: int = fixed_frames_count * self.frame_length
        else:
            data_size: int = self.duration * self.frame_length
        riff_chunk_size = 36 + data_size
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',  # ChunkID
            riff_chunk_size,  # ChunkSize
            b'WAVE',  # Format
            b'fmt ',  # Subchunk1ID
            16,  # Subchunk1Size (16 for PCM)
            self.WAVE_FORMAT_PCM if issubclass(self.data_type, np.integer) else self.WAVE_FORMAT_IEEE_FLOAT, # AudioFormat
            self.channels,  # NumChannels
            self.samples_rate,  # SampleRate
            self.frame_length,  # ByteRate
            self.sample_length,  # BlockAlign
            self.channel_bit_depth,  # BitsPerSample
            b'data',  # Subchunk2ID
            data_size  # Subchunk2Size, use 0 if the data size is unknown or streaming
        )
        return header

    def create_empty_frame(self) -> bytes:
        return bytes(self.frame_length)

    def create_random_frame(self) -> bytes:
        return random.randbytes(self.frame_length)

    def to_json(self):
        return {"channels": self.channels, "channel_bit_depth": self.channel_bit_depth, "samples_rate": self.samples_rate, "duration": self.duration,
                "sample_length": self.sample_length, "frame_length": self.frame_length, "data_type": self.data_type, "data_type_length": self.data_type_length,
                "frame_length_in_data_type": self.frame_length_in_data_type}


class WavAudioNFSK(WavAudio):

    supported_fsk_levels = (2, 4, 8, 16, 32, 64, 128, 256)
    _errors_modes = ("skip", "break",  "ignore")
    _BASE256_CHARSET = (
                         ("0123456789" "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "ĎĚĤĨĴŎŤŪŘŇĜЃꚧᾸỸẐṼẌẄṦ" "Ꜩ₽₳₱€₦₩" "☰☱☲☳☴☵☶☷" "ΔΘΛΞΨΩ") +
                         ("БЁДЖИЙЛПЦЧШЩЪЫЬЭЮЯЭЄЇ" "ႠႡႢႣႤႥႦႧႨႩႪႫႬႭႮႯႰႱႲႳႴႵႶႷႸႹႺႻႼႽႾႿჀჁჂჃჄჅ" "⼚⼜⼝⼞⼟⼠⼢⼣⼤⼥⼦⼧⼨⼩⼪⼫⼬⼭⼮⼯⼰⼱⼲⼳⼴⼵⼶⼷⼸⼹⼺⼻⼼⼄⼈") +
                         ("ᐁᐃᐅᐊᐯᐱᐸᑁᑌᑎᑐᑕᗄᗐᗑᗜᗝᗳⴵ" "ꡀꡁꡂꡃꡄꡅꡆꡇꡈꡉꡊꡋꡌꡍꡎꡏꡐꡑꡒꡓꡔꡕꡖꡗꡘꡙꡚꡛꡜꡝꡞꡟꡠꡡꡢꡣꡤꡥꡦꡧꡨꡩꡪꡫꡬꡭꡮꡯꡰꡱꡲꡳ꡴꡵" "䷀䷒䷓䷚䷾䷁䷂䷄䷅䷕䷆䷇")
                           #"∩∪∫∏∬∭∮∯∰∱∲∳" "䷈䷉䷊䷋䷌䷍䷎䷏䷐䷑䷔䷘䷙䷛䷜䷝䷞䷟䷠䷡䷢䷣䷤䷥䷦䷧䷪䷫䷬䷭䷮䷯䷰䷱䷲䷳䷴䷵䷶䷷䷸䷹䷺䷻䷼䷽䷿")
                        )

    def _base256_chr(self, no: int) -> str:
        return self._BASE256_CHARSET[no]

    def _create_value_symbols(self) -> Tuple[List[int], int]:
        if self.fsk_level not in self.supported_fsk_levels:
            raise ValueError(f"FSK level must be in {self.supported_fsk_levels}, but not {self.fsk_level}!")
        interval: Tuple[int, int] = (int(self.data_type_info.min), int(self.data_type_info.max))
        values_range = abs(interval[0]) + abs(interval[1])
        if values_range < self.fsk_level:
            raise ValueError(f"Levels count({self.fsk_level}) is bigger then values range({values_range}) for selected type({self.data_type})!")
        sub_level = self.fsk_level // 2
        symbols = [math.floor(values_range / self.fsk_level * i) for i in
                   (range(0, self.fsk_level + 1) if interval[0] == 0 else range(-sub_level, sub_level + 1))]
        return ([self.data_type(s) for s in symbols[:sub_level] + symbols[-sub_level:]], self.data_type(symbols[sub_level]))

    def _bits_seq_to_int(self, seq: Iterable[int]) -> int:
        return int("".join(str(bit) for bit in seq), 2)

    def __init__(self, fsk_level: int, full_vs_symbol_samples_count: int, value_symbol_samples_count: int, errors_mode: str = "ignore", **kwargs):
        super().__init__(**kwargs)
        self.full_vs_symbol_samples_count = full_vs_symbol_samples_count
        self.value_symbol_samples_count = value_symbol_samples_count
        self.sync_symbol_samples_count = full_vs_symbol_samples_count - value_symbol_samples_count
        self.errors_mode = "skip" if errors_mode not in self._errors_modes else errors_mode
        self.sync_char_in_str = '█'
        self.error_char_in_str = '❌'
        self.set_fsk_level(fsk_level)

    def set_fsk_level(self, fsk_level: int):
        self.fsk_level = fsk_level
        self.value_symbols, self.sync_symbol = self._create_value_symbols()
        self.frame_full_symbols_count = self._int_div(self.samples_rate, self.full_vs_symbol_samples_count, "samples rate", "samples count for full symbol")
        self.bits_in_value_symbol = int(math.log2(fsk_level))
        if self.bits_in_value_symbol == 1:
            self.result_str_index_shift = 0
        else:
            self.result_str_index_shift = self.bits_in_value_symbol
        self.bits_converter_format = f"{{0:0{self.bits_in_value_symbol}b}}"
        self.value_symbols_seq_length = self.value_symbol_samples_count * self.channels
        self.sync_symbols_seq_length = self.sync_symbol_samples_count * self.channels
        self.value_symbol_duration_sec = self.value_symbol_samples_count / self.samples_rate
        self.sync_symbol_duration_sec = self.sync_symbol_samples_count / self.samples_rate
        self.full_symbol_duration_sec = self.full_vs_symbol_samples_count / self.samples_rate
        self.real_speed_bytes_per_sec = (self.frame_full_symbols_count * self.bits_in_value_symbol) / 8

    def create_random_bits_array(self, bits_length: int) -> np.ndarray:
        return np.random.randint(0, 2, size=bits_length)

    def bits_array_to_str(self, bits: np.ndarray, vs_mode: bool = True) -> str:
        rl, rl_mod = divmod(len(bits), self.bits_in_value_symbol if vs_mode else 1)
        if rl_mod:
            rl += rl_mod
        result = list(self.error_char_in_str * rl)
        counter = 0
        for seq in itertools.batched(bits, self.bits_in_value_symbol if vs_mode else 1):
            result[counter] = self._base256_chr(self._bits_seq_to_int(seq))
            counter += 1
        return "".join(result)

    def fsk_byte_frame_to_str(self, frame: bytes, add_sync_symbols: bool = False, vs_mode: bool = False) -> str:
       return self.fsk_frame_to_str(np.frombuffer(frame, dtype=self.data_type), add_sync_symbols, vs_mode)

    def fsk_frame_to_str(self, frame: np.ndarray, add_sync_symbols: bool = False, vs_mode: bool = False) -> str:
        if len(frame) != self.frame_length_in_data_type:
            raise ValueError(f"Target frame length({len(frame)}) not eq expected frame length({self.frame_length//self.data_type_length}) casted to data type({self.data_type})")
        if vs_mode:
            result_values_len = self.frame_full_symbols_count
        else:
            result_values_len = self.bits_in_value_symbol * self.frame_full_symbols_count
        result = list( (self.error_char_in_str * result_values_len) + (self.error_char_in_str * (self.frame_full_symbols_count if add_sync_symbols else 0)))
        counter = 0
        res_index = 0
        while counter < len(frame):
            try:
                if vs_mode:
                    result[res_index] = self._base256_chr(self.value_symbols.index(frame[counter]))
                    res_index += 1
                else:
                    result[res_index:res_index + self.result_str_index_shift] = self.bits_converter_format.format(self.value_symbols.index(frame[counter]))
                    res_index += self.bits_in_value_symbol
                counter += self.value_symbols_seq_length
            except ValueError:
                    if frame[counter] == self.sync_symbol:
                        counter += self.sync_symbols_seq_length
                        if add_sync_symbols:
                            result[res_index] = self.sync_char_in_str
                            res_index += 1
                    else:
                        counter += 1
                        if add_sync_symbols:
                            result[res_index] = self.error_char_in_str
                            res_index += 1
        return "".join(result)

    def create_fsk_frame(self, bits: np.ndarray) -> np.ndarray:
        frame: np.ndarray = np.zeros(self.frame_length_in_data_type, dtype=self.data_type)
        counter = 0
        for seq in itertools.batched(bits, self.bits_in_value_symbol):
            v_sym = self.value_symbols[self._bits_seq_to_int(seq)]
            frame[counter: counter + self.value_symbols_seq_length] = v_sym
            counter += self.value_symbols_seq_length
            frame[counter: counter + self.sync_symbols_seq_length] = self.sync_symbol
            counter += self.sync_symbols_seq_length
            # for i in range(self.value_symbols_seq_length):
            #     frame[counter+i] = v_sym
            # counter += self.value_symbols_seq_length
            # for i in range(self.sync_symbols_seq_length):
            #     frame[counter+i] = self.sync_symbol  # TODO: bug if uses not int16
            # counter += self.sync_symbols_seq_length
        return frame

    def str_to_bits_array(self, text: str) -> np.ndarray:
        return np.unpackbits(np.frombuffer(text.encode('utf-8'), dtype=np.uint8))

    def bytes_to_bits_array(self, bytes_seq: bytes) -> np.ndarray:
        return np.unpackbits(np.frombuffer(bytes_seq, dtype=np.uint8))

    def to_json(self):
        return {**super().to_json(), "fsk_level": self.fsk_level, "full_vs_symbol_samples_count": self.full_vs_symbol_samples_count, "value_symbol_samples_count": self.value_symbol_samples_count,
                   "sync_symbol_samples_count": self.sync_symbol_samples_count, "frame_full_symbols_count": self.frame_full_symbols_count, "bits_in_value_symbol": self.bits_in_value_symbol, "real_speed_bytes_per_sec": self.real_speed_bytes_per_sec,
                   "sync_char_in_str": self.sync_char_in_str, "error_char_in_str": self.error_char_in_str, "value_symbols_seq_length": self.value_symbols_seq_length, "sync_symbols_seq_length": self.sync_symbols_seq_length,
                   "result_str_index_shift": self.result_str_index_shift, "value_symbol_duration_sec": self.value_symbol_duration_sec, "sync_symbol_duration_sec": self.sync_symbol_duration_sec,
                   "full_symbol_duration_sec": self.full_symbol_duration_sec, "base256_charset": self._BASE256_CHARSET, "value_symbols": self.value_symbols, "sync_symbol": self.sync_symbol,
                   "supported_fsk_levels": self.supported_fsk_levels, "supported_data_types": self._supported_data_types, "errors_mode": self.errors_mode}


class SimpleLogger:
    def __init__(self, id: str, wav: WavAudio, io: Callable[[str,...], None] = None):
            self.id = id
            self.wav = wav
            self.io = io if io else lambda s: None

    def msg(self, msg: str):
        if self.io:
            self.io(f"[{self.id}] {msg}")

    def msgl(self, l: Callable[[], str]):
        if self.io:
            self.io(f"[{self.id}] {l()}")

    def stream_msg(self, sec: int, direction: str, counted: int, counted_type: str, descr: str, charset_base: int, raw_msg: str):
        self.msg(f"[sec={sec}] {direction} {counted} {counted_type} for next {descr}[charset_base={charset_base},length={len(raw_msg)}]: {raw_msg}")

    def stream_msgs_block(self, i: int, bits: np.ndarray, fsk_frame: np.ndarray):
        if self.io is None:
            return
        self.stream_msg(i, "Received", len(bits),  "bits", "frame", 2, self.wav.bits_array_to_str(bits, False))
        self.stream_msg(i, "Received", len(bits), "bits", "frame", self.wav.fsk_level, self.wav.bits_array_to_str(bits))
        self.stream_msg(i, "Yielding", fsk_frame.nbytes, "bytes", "FSK frame(with sync symbols)", 2, self.wav.fsk_frame_to_str(fsk_frame, True))
        self.stream_msg(i, "Yielding", fsk_frame.nbytes, "bytes", "FSK frame(without sync symbols)", 2, self.wav.fsk_frame_to_str(fsk_frame, False))
        self.stream_msg(i, "Yielding", fsk_frame.nbytes, "bytes", "FSK frame(with sync symbols)", self.wav.fsk_level, self.wav.fsk_frame_to_str(fsk_frame, True, True))
        self.stream_msg(i, "Yielding", fsk_frame.nbytes, "bytes", "FSK frame(without sync symbols)", self.wav.fsk_level, self.wav.fsk_frame_to_str(fsk_frame, False, True))

    def seq(self, data: Union[str, bytes], stay_len: int = 8, stay_at_end: bool = True) -> str:
        l = len(data)
        prefix = f"[Length={l}] "
        if l < stay_len * 2:
            return f"{prefix}{data}"
        else:
            return f"{prefix}{data[0:stay_len]}...{data[len(data) - stay_len:] if stay_at_end else ""}"


class AsyncAudioStream:
    def __init__(self, wav: WavAudio, crypter: Optional[AESBase], req_range = None, debug: bool = True):
        self.stream_uuid: str = ''.join(random.choices(string.hexdigits, k=8))
        self.wav = wav
        self.frames_delay = 1
        self.crypter = crypter
        self.expected_frames_count = 0
        self._req_range = req_range
        self.logger = SimpleLogger(self.stream_uuid, io=print if debug else None, wav=self.wav)
        self.frame_body_length = self.wav.frame_length

    def _init_generators(self):
        if self.crypter:
            self.frame_body_length = self.wav.frame_length - self.crypter.additional_payload_length
            if self.frame_body_length <= 0:
                raise ValueError(f"Sample body length: {self.frame_body_length} must be bigger then: {self.crypter.additional_payload_length}")
            if self.crypter.text:
                self.sample_gen = self._text_aes_crypted_fsk_frames_gen()
                next(self.sample_gen)
            else:
                if isinstance(self.wav, WavAudioNFSK):
                    self.sample_gen = self._random_aes_fsk_frames_gen()
                else:
                    self.sample_gen = self._random_aes_crypted_frames_gen()
        else:
            if isinstance(self.wav, WavAudioNFSK):
                self.sample_gen = self._random_fsk_frames_gen()
            else:
                self.sample_gen = self._random_frames_gen()

    def _padded_bits_gen(self, source_bits_array: np.ndarray, bits_per_iteration: int) -> Generator[np.ndarray, None, None]:
        source_bits_array_length = len(source_bits_array)
        counter = 0
        while counter < source_bits_array_length:
            if source_bits_array_length - counter > bits_per_iteration:
                yield source_bits_array[counter:counter + bits_per_iteration]
                counter += bits_per_iteration
            else:
                sub_array = source_bits_array[counter:]
                pad_bit = 0 if sub_array[-1] == 1 else 1
                self.logger.msgl(lambda: f"Padding last yielding bits seq with {bits_per_iteration-len(sub_array)} bits: {pad_bit}")
                padded_array = np.pad(
                    sub_array,
                    pad_width=(0, bits_per_iteration - len(sub_array)),
                    mode='constant',
                    constant_values=pad_bit
                )
                counter += bits_per_iteration
                yield padded_array

    def _text_aes_crypted_fsk_frames_gen(self) -> Generator[bytes, None, None]:
        self.logger.msgl(lambda: f"Received Plain Text: {self.logger.seq(self.crypter.text, 32)}, Using {self.crypter.__class__.__name__},  Additional AES bytes count: {self.crypter.additional_payload_length}...")
        encrypted_text_bytes: bytes = self.crypter.encrypt(self.crypter.text)
        encrypted_text_bits: np.ndarray = self.wav.bytes_to_bits_array(encrypted_text_bytes)
        bits_as_full_symbols_in_frame: int = self.wav.frame_full_symbols_count*self.wav.bits_in_value_symbol
        self.expected_frames_count = math.ceil(len(encrypted_text_bits) / self.wav.frame_full_symbols_count / self.wav.bits_in_value_symbol)
        self.logger.msgl(lambda: f"AES crypted bytes: {self.logger.seq(encrypted_text_bytes)}, AES crypted bits: {self.logger.seq(encrypted_text_bits)}, "
                        f"Bits in frame(as full symbols): {bits_as_full_symbols_in_frame}, Expected frames count: {self.expected_frames_count}")
        yield
        for i, padded_bits_per_frame in enumerate(self._padded_bits_gen(encrypted_text_bits, bits_as_full_symbols_in_frame), 1):
            fsk_frame: np.ndarray = self.wav.create_fsk_frame(padded_bits_per_frame)
            self.logger.stream_msgs_block(i, padded_bits_per_frame, fsk_frame)
            yield fsk_frame.tobytes()

    def _random_frames_gen(self) -> Generator[bytes, None, None]:
        while True:
            yield self.wav.create_random_frame()

    def _random_aes_crypted_frames_gen(self, fixed_random_bytes_length: int = 0) -> Generator[bytes, None, None]:
        if not fixed_random_bytes_length:
            fixed_random_bytes_length = self.frame_body_length
        while True:
            yield self.crypter.encrypt(random.randbytes(fixed_random_bytes_length))

    def _random_fsk_frames_gen(self) -> Generator[bytes, None, None]:
        for i in count(start=1):
            bits: np.ndarray = self.wav.create_random_bits_array(self.wav.frame_full_symbols_count*self.wav.bits_in_value_symbol)
            fsk_frame: np.ndarray = self.wav.create_fsk_frame(bits)
            self.logger.stream_msgs_block(i, bits, fsk_frame)
            yield fsk_frame.tobytes()

    def _random_aes_fsk_frames_gen(self) -> Generator[bytes, None, None]:
        aes_crypted_frames_gen = self._random_aes_crypted_frames_gen()
        sec = 1
        while True:
            for bits in self._padded_bits_gen(self.wav.bytes_to_bits_array(next(aes_crypted_frames_gen)), self.wav.frame_full_symbols_count * self.wav.bits_in_value_symbol):
                fsk_frame: np.ndarray = self.wav.create_fsk_frame(bits)
                self.logger.stream_msgs_block(sec, bits, fsk_frame)
                yield fsk_frame.tobytes()
                sec += 1



    def _sync_generator_wrapper(self) -> Generator[bytes, None, None]:
        loop = asyncio.new_event_loop()
        stream_gen = self._async_stream_generator()
        try:
            while True:
                try:
                    chunk = loop.run_until_complete(stream_gen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    def wav_aes_nfsk_decrypt(self, data: bytes) -> Optional[str]:
        # Reading raw data as memory stream
        wav_stream = io.BytesIO(data)
        with wave.open(wav_stream, "rb") as wav_file:

            # Parsing wav header
            params = wav_file.getparams()
            channels = params.nchannels
            channel_byte_length = params.sampwidth
            channel_bit_depth = params.sampwidth * 8
            samples_rate = params.framerate
            sample_byte_length = channels * channel_byte_length
            frame_byte_length = sample_byte_length * samples_rate
            frame_length_in_data_type = frame_byte_length // channel_byte_length
            self.logger.msgl(lambda: f'Wav header parsed params: { {"channels": channels, "channel_byte_length": channel_byte_length, "channel_bit_depth": channel_bit_depth,
                                                                    "samples_rate": samples_rate, "sample_byte_length": sample_byte_length, "frame_byte_length": frame_byte_length,
                                                                    "frame_length_in_data_type": frame_length_in_data_type} }')

            # Detecting data type and audio format
            audio_format = struct.unpack("<H", data[20:22])[0]
            if audio_format == self.wav.WAVE_FORMAT_IEEE_FLOAT:
                data_type_name = f"float{channel_bit_depth}"
            else:
                if audio_format != self.wav.WAVE_FORMAT_PCM:
                    _message = f"Unknown AudioFormat: {audio_format}"
                    if self.wav.errors_mode == "break":
                        raise ValueError(_message)
                    self.logger.msg(f"{_message}, trying WAVE_FORMAT_PCM")
                data_type_name = "uint8" if channel_byte_length == 1 else f"int{channel_bit_depth}"
            data_type: Type[np.integer, np.floating] = np.dtype(data_type_name).type
            self.logger.msg(f"Using {data_type_name} as data type")

            # Converting raw wav data body to np.ndarray of detected data type
            wav_body: np.ndarray = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=data_type)

        # For EACH frame
        bits_summary: List[np.ndarray] = list()
        for frame_counter, frame_shift in enumerate(range(0, len(wav_body), frame_length_in_data_type)):
            frame: np.ndarray = wav_body[frame_shift: frame_shift + frame_length_in_data_type]

            # Detecting N-FSK params(level,symbols, etc)
            frame_all_symbols = np.unique(frame)
            frame_using_sync_symbol = frame_all_symbols.size % 2 != 0
            if frame_using_sync_symbol:
                frame_sync_symbol: data_type = frame_all_symbols[frame_all_symbols.size // 2]
                frame_value_symbols: List[data_type] = list(np.delete(frame_all_symbols, frame_all_symbols.size // 2))
            else:
                self.logger.msg("Sync symbol not found!")
                frame_sync_symbol = None
                frame_value_symbols: List[data_type] = list(frame_all_symbols)
            frame_fsk_level = len(frame_value_symbols)

            # FSK level check
            if frame_fsk_level not in self.wav.supported_fsk_levels:
                _message = f"[Frame={frame_counter}] Unsupported FSK level: {frame_fsk_level}"
                if self.wav.errors_mode == "break":
                    raise ValueError(_message)
                elif self.wav.errors_mode == "skip":
                    self.logger.msg(f"{_message}, skipping current frame!")
                else:
                    self.logger.msg(f"{_message}, ignoring current frame!")

            frame_bits_in_value_symbol = int(math.log2(len(frame_value_symbols)))
            self.logger.msgl(lambda: f'[Frame={frame_counter}] N-FSK params: { {"fsk_level": frame_fsk_level, "bits_in_value_symbol": frame_bits_in_value_symbol,
                                                                                "sync_symbol": frame_sync_symbol, "value_symbols": frame_value_symbols} }')

            # Extracting only value symbols seq then converting its to bits
            frame_symbols_seq: np.ndarray = frame[np.concatenate(([True], frame[1:] != frame[:-1]))]
            self.logger.msg(f"[Frame={frame_counter}] All detected symbols sequence length: {frame_symbols_seq.size}")
            if frame_sync_symbol is not None:
                frame_symbols_seq = frame_symbols_seq[frame_symbols_seq != frame_sync_symbol]
            self.logger.msg(f"[Frame={frame_counter}] All detected value symbols sequence length: {frame_symbols_seq.size}")
            frame_bits_from_value_symbols: List[np.ndarray] = [np.fromiter(np.binary_repr(frame_value_symbols.index(s), width=frame_bits_in_value_symbol), dtype=int) for s in frame_symbols_seq]
            bits_summary += frame_bits_from_value_symbols

        # Concatenating all bit seqs from all frames
        all_bits: np.ndarray = np.concatenate(bits_summary)
        self.logger.msg(f"Concatenated from all frames bits sequence length: {all_bits.size}")

        # Detecting bits padding and all unpadding bits seq
        last_bit = all_bits[-1]
        unpadding_mask = (all_bits[::-1] == last_bit)
        same_bits_at_end = np.argmax(~unpadding_mask) if not np.all(unpadding_mask) else len(all_bits)
        if same_bits_at_end > 5:  # TODO: May be change
            self.logger.msg(f"Concatenated bits sequence looks like padded, last {same_bits_at_end} has same value: {last_bit}")
            all_bits = all_bits[:all_bits.size - same_bits_at_end]
            self.logger.msg(f"Unpadded concatenated bits sequence length: {all_bits.size}")

        # Converting bits seq to bytes
        all_bytes: bytes = np.packbits(all_bits).tobytes()
        self.logger.msg(f"Concatenated bits sequence converted to bytes length: {len(all_bytes)}")

        plain_text: str = self.crypter.decrypt(all_bytes)
        return plain_text

    def to_json(self):
        return {"stream_uuid": self.stream_uuid, "expected_frames_count": self.expected_frames_count,
                "wav": self.wav.to_json(), "crypter": self.crypter.to_json() if self.crypter else {}}

    async def _async_stream_generator(self) -> AsyncGenerator[bytes, None]:
        #if str(self._req_range) == "bytes=0-":
        yield self.wav.create_wav_header(self.expected_frames_count)

        # if self._req_range is None:
        #     return

        self.logger.msgl(lambda: f"Stream initiated with config: {self.to_json()}")
        #yield self.wav.create_wav_header(self.expected_frames_count)
        for i in count(start=1):
            try:
                yield next(self.sample_gen)
            except StopIteration:
                return
            if i == self.wav.duration:
                return
            await asyncio.sleep(self.frames_delay)

    def start(self) -> Response:
        if self.wav.info_only:
            return Response(json.dumps(self.to_json(), indent=4, default=str, ensure_ascii=False), mimetype='application/json')
        self.logger.msg(f"_req_range: {self._req_range}")
        self._init_generators()
        if self._req_range is None:
             return Response(self.wav.create_wav_header(), mimetype='audio/wav')
        # if str(self._req_range) == "bytes=0-":

        return Response(self._sync_generator_wrapper(), mimetype='audio/wav')