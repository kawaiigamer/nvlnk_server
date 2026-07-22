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
from typing import Optional, Generator, AsyncGenerator, Union, List, Iterable, Tuple, Dict, Self

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
        raise NotImplemented

    def encrypt(self, data: Union[bytes, str]) -> bytes:
        raise NotImplemented

    def decrypt(self, data: bytes) -> str:
        raise NotImplemented

    @staticmethod
    def from_config(config: Dict[str, Union[str, int]]) -> Self:
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


class AESCBC(AESBase):
    def __init__(self,  **kwargs):
        super().__init__(**kwargs)

    @property
    def additional_payload_length(self) -> int:
        return self.iv_length

    def encrypt(self, data: Union[bytes, str]) -> bytes:
        if isinstance(data, str):
            data = data.encode()
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

    def _int_div(self, x: int, y: int, x_name: str, y_name_: str) -> int:
        r, r_mod = divmod(x, y)
        if r_mod != 0:
            raise ValueError(f"Divmod of {x_name} on {y_name_} must be integer({x}/{y}={r}+mod({r_mod}))")
        return r

    def __init__(self, channels: int, channel_bit_depth: int, samples_rate: int, data_type: str = "int16", duration: int = 0, info_only:str = "false"):
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
            1,  # AudioFormat (1 for uncompressed PCM)
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


class WavAudioFSK(WavAudio):

    _supported_fsk_levels = (2, 4, 8, 16, 32, 64, 128, 256)
    _BASE256_CHARSET = (
                         ("0123456789" "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "ĎĚĤĨĴŎŤŪŘŇĜЃꚧᾸỸẐṼẌẄṦ" "Ꜩ₽₳₱€₦₩" "☰☱☲☳☴☵☶☷" "ΔΘΛΞΨΩ") +
                         ("БЁДЖИЙЛПЦЧШЩЪЫЬЭЮЯЭЄЇ" "ႠႡႢႣႤႥႦႧႨႩႪႫႬႭႮႯႰႱႲႳႴႵႶႷႸႹႺႻႼႽႾႿჀჁჂჃჄჅ" "⼚⼜⼝⼞⼟⼠⼢⼣⼤⼥⼦⼧⼨⼩⼪⼫⼬⼭⼮⼯⼰⼱⼲⼳⼴⼵⼶⼷⼸⼹⼺⼻⼼⼄⼈") +
                         ("ᐁᐃᐅᐊᐯᐱᐸᑁᑌᑎᑐᑕᗄᗐᗑᗜᗝᗳⴵ" "ꡀꡁꡂꡃꡄꡅꡆꡇꡈꡉꡊꡋꡌꡍꡎꡏꡐꡑꡒꡓꡔꡕꡖꡗꡘꡙꡚꡛꡜꡝꡞꡟꡠꡡꡢꡣꡤꡥꡦꡧꡨꡩꡪꡫꡬꡭꡮꡯꡰꡱꡲꡳ꡴꡵" "䷀䷒䷓䷚䷾䷁䷂䷄䷅䷕䷆䷇")
                           #"∩∪∫∏∬∭∮∯∰∱∲∳" "䷈䷉䷊䷋䷌䷍䷎䷏䷐䷑䷔䷘䷙䷛䷜䷝䷞䷟䷠䷡䷢䷣䷤䷥䷦䷧䷪䷫䷬䷭䷮䷯䷰䷱䷲䷳䷴䷵䷶䷷䷸䷹䷺䷻䷼䷽䷿")
                        )

    def _base256_chr(self, no: int) -> str:
        return self._BASE256_CHARSET[no]

    def _create_value_symbols(self) -> Tuple[List[int], int]:   # TODO: fix bug incorrect max value(+1) with 64bit types
        if self.fsk_level not in self._supported_fsk_levels:
            raise ValueError(f"FSK level must be in {self._supported_fsk_levels}, but not {self.fsk_level}!")
        interval: Tuple[int, int] = (int(self.data_type_info.min), int(self.data_type_info.max))
        values_range = abs(interval[0]) + abs(interval[1])
        if values_range < self.fsk_level:
            raise ValueError(f"Levels count({self.fsk_level}) is bigger then values range({values_range}) for selected type({self.data_type})!")
        sub_level = self.fsk_level // 2
        symbols = [math.floor(values_range / self.fsk_level * i) for i in
                   (range(0, self.fsk_level + 1) if interval[0] == 0 else range(-sub_level, sub_level + 1))]
        return ([self.data_type(s) for s in symbols[:sub_level] + symbols[-sub_level:]], self.data_type(symbols[sub_level]))

    def __init__(self, fsk_level: int, full_vs_symbol_samples_count: int, value_symbol_samples_count: int, **kwargs):
        super().__init__(**kwargs)
        self.fsk_level = fsk_level
        self.value_symbols, self.sync_symbol = self._create_value_symbols()
        self.full_vs_symbol_samples_count = full_vs_symbol_samples_count
        self.value_symbol_samples_count = value_symbol_samples_count
        self.sync_symbol_samples_count = full_vs_symbol_samples_count - value_symbol_samples_count
        self.frame_full_symbols_count = self._int_div(self.samples_rate, full_vs_symbol_samples_count, "samples rate", "samples count for full symbol")
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
        self.sync_char_in_str = '█'
        self.error_char_in_str = '❌'
        self.real_speed_bytes_per_sec = (self.frame_full_symbols_count * self.bits_in_value_symbol) / 8

    def _bits_seq_to_int(self, seq: Iterable[int]) -> int:
        return int("".join(str(bit) for bit in seq), 2)

    def create_random_bits_array(self, bits_length: int) -> np.ndarray:
        return np.random.randint(0, 2, size=bits_length)

    def bits_array_to_01_str(self, nparray_bits: np.ndarray) -> str:
        result = list(self.error_char_in_str * len(nparray_bits))
        for i, b in enumerate(nparray_bits):
            if b:
                result[i] = '1'
            else:
                result[i] = '0'
        return "".join(result)

    def bits_array_to_vs_str(self, nparray_bits: np.ndarray) -> str:
        rl, rl_mod = divmod(len(nparray_bits), self.bits_in_value_symbol)
        if rl_mod:
            rl += rl_mod
        result = list(self.error_char_in_str *  rl)
        counter = 0
        for seq in itertools.batched(nparray_bits, self.bits_in_value_symbol):
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
            for i in range(self.value_symbols_seq_length):
                frame[counter+i] = v_sym
            counter += self.value_symbols_seq_length
            for i in range(self.sync_symbols_seq_length):
                frame[counter+i] = self.sync_symbol
            counter += self.sync_symbols_seq_length
        return frame

    def str_to_bits_array(self, text: str) -> np.ndarray:
        return np.unpackbits(np.frombuffer(text.encode('utf-8'), dtype=np.uint8))

    def bits_array_to_str(self, bits_array: np.ndarray) -> str:
        return np.packbits(bits_array).tobytes().decode('utf-8')

    def bytes_to_bits_array(self, bytes_seq: bytes) -> np.ndarray:
        return np.unpackbits(np.frombuffer(bytes_seq, dtype=np.uint8))

    def to_json(self):
        j = super().to_json()
        j.update({ "fsk_level": self.fsk_level, "full_vs_symbol_samples_count": self.full_vs_symbol_samples_count, "value_symbol_samples_count": self.value_symbol_samples_count,
                   "sync_symbol_samples_count": self.sync_symbol_samples_count, "frame_full_symbols_count": self.frame_full_symbols_count, "bits_in_value_symbol": self.bits_in_value_symbol, "real_speed_bytes_per_sec": self.real_speed_bytes_per_sec,
                   "sync_char_in_str": self.sync_char_in_str, "error_char_in_str": self.error_char_in_str, "value_symbols_seq_length": self.value_symbols_seq_length, "sync_symbols_seq_length": self.sync_symbols_seq_length,
                   "result_str_index_shift": self.result_str_index_shift, "value_symbol_duration_sec": self.value_symbol_duration_sec, "sync_symbol_duration_sec": self.sync_symbol_duration_sec,
                   "full_symbol_duration_sec": self.full_symbol_duration_sec, "base256_charset": self._BASE256_CHARSET, "value_symbols": self.value_symbols, "sync_symbol": self.sync_symbol,
                   "supported_fsk_levels": self._supported_fsk_levels, "supported_data_types": self._supported_data_types})
        return j


class AsyncAudioStream:
    def __init__(self, wav: WavAudio, crypter: Optional[AESBase], debug: bool = False):
        self.stream_uuid: str = ''.join(random.choices(string.hexdigits, k=8))
        self.wav = wav
        self.frames_delay = 1
        self.crypter = crypter
        self.frames_count = 0
        if crypter:
            self.frame_body_length = self.wav.frame_length - crypter.additional_payload_length
            if self.frame_body_length <= 0:
                raise ValueError(f"Sample body length: {self.frame_body_length} must be bigger then: {crypter.additional_payload_length}")
            if crypter.text:
                self.sample_gen = self.__text_aes_crypted_fsk_frames_gen()
            else:
                self.sample_gen = self.__random_aes_crypted_frames_gen()
        else:
            if isinstance(self.wav, WavAudioFSK):
                if debug:
                    self.sample_gen = self.__random_fsk_frames_gen_dbg()
                else:
                    self.sample_gen = self.__random_fsk_frames_gen()
            else:
                self.sample_gen = self.__random_frames_gen()

    def _debug_msg(self, sec: int, counted: int, counted_type: str, descr: str, charset_len: int, raw_msg: str):
        print(f"[{self.stream_uuid}][sec={sec}] Generated {counted} {counted_type} for next {descr}[charset_len={charset_len},length={len(raw_msg)}]: {raw_msg}")

    def __padded_bits_gen(self, source_bits_array: np.ndarray, bits_per_iteration: int) -> Generator[np.ndarray, None, None]:
        source_bits_array_length = len(source_bits_array)
        counter = 0
        while counter < source_bits_array_length:
            if source_bits_array_length - counter > bits_per_iteration:
                yield source_bits_array[counter:counter + bits_per_iteration]
                counter += bits_per_iteration
            else:
                # print(f"ret {source_bits_array_length - counter} < {per_frame}, source_bits_array_length: {source_bits_array_length}")
                sub_array = source_bits_array[counter:]
                #print(f"sub_array: {sub_array}, ends with {sub_array[-1]}, {len(sub_array)}")
                # pad_val =
                padded_array = np.pad(
                    sub_array,
                    pad_width=(0, bits_per_iteration - len(sub_array)),
                    mode='constant',
                    constant_values=0 if sub_array[-1] == 1 else 1
                )
                counter += bits_per_iteration
                # print(f"padded_array: {padded_array}, {len(padded_array)}")
                yield padded_array

    def __text_aes_crypted_fsk_frames_gen(self) -> Generator[bytes, None, None]:
        encrypted_text_bytes: bytes = self.crypter.encrypt(self.crypter.text)
        encrypted_text_bits: np.ndarray = self.wav.bytes_to_bits_array(encrypted_text_bytes)
        bits_as_full_symbols_in_frame: int = self.wav.frame_full_symbols_count*self.wav.bits_in_value_symbol   # TODO: additional
        self.frames_count = math.ceil(len(encrypted_text_bits) / self.wav.frame_length * 8)
        for padded_bits_per_frame in self.__padded_bits_gen(encrypted_text_bits, bits_as_full_symbols_in_frame):
            fsk_frame: np.ndarray = self.wav.create_fsk_frame(padded_bits_per_frame)
            yield fsk_frame.tobytes()

    def __random_aes_crypted_frames_gen(self) -> Generator[bytes, None, None]:
        while True:
            yield self.crypter.encrypt(random.randbytes(self.frame_body_length))

    def __random_frames_gen(self) -> Generator[bytes, None, None]:
        while True:
            yield self.wav.create_random_frame()

    def __random_fsk_frames_gen(self) -> Generator[bytes, None, None]:
        while True:
            bits: np.ndarray = self.wav.create_random_bits_array(self.wav.frame_full_symbols_count*self.wav.bits_in_value_symbol)
            fsk_frame: np.ndarray = self.wav.create_fsk_frame(bits)
            yield fsk_frame.tobytes()

    def __random_fsk_frames_gen_dbg(self) -> Generator[bytes, None, None]:
        print(f"[{self.stream_uuid}] Stream initiated with config: {self.wav.to_json()}")
        i = 0
        while True:
            bits: np.ndarray = self.wav.create_random_bits_array(self.wav.frame_full_symbols_count*self.wav.bits_in_value_symbol)
            fsk_frame: np.ndarray = self.wav.create_fsk_frame(bits)

            self._debug_msg(i, len(bits), "bits", "frame", 2, self.wav.bits_array_to_01_str(bits))
            self._debug_msg(i, len(bits), "bits", "frame", self.wav.fsk_level, self.wav.bits_array_to_vs_str(bits))
            self._debug_msg(i, len(fsk_frame), "bytes", "FSK frame(with sync symbols)", 2, self.wav.fsk_frame_to_str(fsk_frame, True))
            self._debug_msg(i, len(fsk_frame), "bytes", "FSK frame(without sync symbols)", 2, self.wav.fsk_frame_to_str(fsk_frame, False))
            self._debug_msg(i, len(fsk_frame), "bytes", "FSK frame(with sync symbols)", self.wav.fsk_level, self.wav.fsk_frame_to_str(fsk_frame, True, True))
            self._debug_msg(i, len(fsk_frame), "bytes", "FSK frame(without sync symbols)", self.wav.fsk_level, self.wav.fsk_frame_to_str(fsk_frame, False, True))

            yield fsk_frame.tobytes()
            i += 1

    async def __stream_generator(self) -> AsyncGenerator[bytes, None]:
        yield self.wav.create_wav_header(self.frames_count)
        for i in count(start=1):
            try:
                yield next(self.sample_gen)
            except StopIteration:
                return
            if i == self.wav.duration:
                return
            await asyncio.sleep(self.frames_delay)

    def __sync_generator_wrapper(self) -> Generator[bytes, None, None]:
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

    def wav_aes_fsk_decrypt(self, data: bytes) -> Response: # TODO: continue
        wav_stream = io.BytesIO(data)
        with wave.open(wav_stream, "rb") as wav_file:
            frame_size = wav_file.getsampwidth() * wav_file.getnchannels()
            audio_payload = wav_file.readframes(wav_file.getnframes())
            for i in range(0, len(audio_payload), frame_size):
                frame_bytes = audio_payload[i: i + frame_size]

        return Response("nothing", mimetype='plain/text')

    def start(self) -> Response:
        if self.wav.info_only:
            j = {"stream_uuid": self.stream_uuid}
            j.update(self.wav.to_json())
            return Response(json.dumps(j, indent=4, default=str, ensure_ascii=False), mimetype='application/json')
        return Response(self.__sync_generator_wrapper(), mimetype='audio/wav')
