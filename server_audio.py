import itertools
import math
import random
import struct
from typing import Union, Tuple, List, Iterable, Dict, Any

import numpy as np

from server_logging import EndpointLogger


class WavAudio:
    supported_data_types = ("int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float16", "float32", "float64")
    WAVE_FORMAT_PCM = 1
    WAVE_FORMAT_IEEE_FLOAT = 3

    def _int_div(self, x: int, y: int, x_name: str, y_name_: str) -> int:
        r, r_mod = divmod(x, y)
        if r_mod != 0:
            raise ValueError(f"Divmod of {x_name} on {y_name_} must be integer({x}/{y}={r}+mod({r_mod}))")
        return r

    def __init__(self, logger: EndpointLogger, channels: int, channel_bit_depth: int, samples_rate: int, data_type: str = "int16", duration: int = 0, info_only: str = "false", **kwargs):
        self.logger = logger
        self.info_only = info_only.lower() == 'true'
        self.channels = channels
        self.channel_bit_depth = channel_bit_depth
        self.samples_rate = samples_rate
        self.sample_length = self.channels * int(self.channel_bit_depth // 8)
        self.frame_length = self.sample_length * self.samples_rate
        if data_type not in self.supported_data_types:
            raise ValueError(f"Selected data type: {data_type} is not supported!")
        try:
            self.data_type: Union[np.integer, np.floating] = np.dtype(data_type).type
        except TypeError:
            self.logger.exception(f"Data type {data_type} is not supported, using int16 instead")
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
    max_dynamic_smoothing_diff = 32.0
    _errors_modes = ("skip", "break",  "ignore")
    _BASE256_CHARSET = (
                         ("0123456789" "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "ĎĚĤĨĴŎŤŪŘŇĜЃꚧᾸỸẐṼẌẄṦ" "Ꜩ₽₳₱€₦₩" "☰☱☲☳☴☵☶☷" "ΔΘΛΞΨΩ") +
                         ("БЁДЖИЙЛПЦЧШЩЪЫЬЭЮЯЭЄЇ" "ႠႡႢႣႤႥႦႧႨႩႪႫႬႭႮႯႰႱႲႳႴႵႶႷႸႹႺႻႼႽႾႿჀჁჂჃჄჅ" "⼚⼜⼝⼞⼟⼠⼢⼣⼤⼥⼦⼧⼨⼩⼪⼫⼬⼭⼮⼯⼰⼱⼲⼳⼴⼵⼶⼷⼸⼹⼺⼻⼼⼄⼈") +
                         ("ᐁᐃᐅᐊᐯᐱᐸᑁᑌᑎᑐᑕᗄᗐᗑᗜᗝᗳⴵ" "ꡀꡁꡂꡃꡄꡅꡆꡇꡈꡉꡊꡋꡌꡍꡎꡏꡐꡑꡒꡓꡔꡕꡖꡗꡘꡙꡚꡛꡜꡝꡞꡟꡠꡡꡢꡣꡤꡥꡦꡧꡨꡩꡪꡫꡬꡭꡮꡯꡰꡱꡲꡳ꡴꡵" "䷀䷒䷓䷚䷾䷁䷂䷄䷅䷕䷆䷇")
                           #"∩∪∫∏∬∭∮∯∰∱∲∳" "䷈䷉䷊䷋䷌䷍䷎䷏䷐䷑䷔䷘䷙䷛䷜䷝䷞䷟䷠䷡䷢䷣䷤䷥䷦䷧䷪䷫䷬䷭䷮䷯䷰䷱䷲䷳䷴䷵䷶䷷䷸䷹䷺䷻䷼䷽䷿")
                        )

    def _base256_chr(self, no: int) -> str:
        return self._BASE256_CHARSET[no]

    def _bits_seq_to_int(self, seq: Iterable[int]) -> int:
        return int("".join(str(bit) for bit in seq), 2)

    # def _create_value_symbols(self) -> Tuple[List[Union[int, float]], Union[int, float]]:
    #     interval: Tuple[int, int] = (int(self.data_type_info.min), int(self.data_type_info.max))
    #     values_range = (abs(interval[0]) + abs(interval[1]))/self.smoothing
    #     if values_range < self.fsk_level:
    #         raise ValueError(f"Levels count({self.fsk_level}) is bigger then values range({values_range}) for selected type({self.data_type})!")
    #     sub_level = self.fsk_level // 2
    #     symbols = [math.floor(values_range / self.fsk_level * i) for i in
    #                (range(0, self.fsk_level + 1) if interval[0] == 0 else range(-sub_level, sub_level + 1))]
    #     # Special fix for 64 bit types
    #     if np.dtype(self.data_type).itemsize == 8:
    #         symbols[-1] -= 1
    #     return ([self.data_type(s) for s in symbols[:sub_level] + symbols[-sub_level:]], self.data_type(symbols[sub_level]))

    def _create_value_symbols(self) -> Tuple[List, float]:
        sub_level =  self.fsk_level // 2
        if np.issubdtype( self.data_type, np.integer):
            info = np.iinfo( self.data_type)
            # Для целых чисел linspace безопасен, так как нет бесконечностей
            symbols = np.linspace(info.min, info.max,  self.fsk_level + 1, dtype= self.data_type)
            center_symbol = symbols[sub_level]
            result_symbols = np.concatenate((symbols[:sub_level], symbols[sub_level + 1:]))
            return result_symbols.tolist(), float(center_symbol)
        else:
            info = np.finfo(self.data_type)
            step = np.float64(info.max) / sub_level
            indices = np.arange(-sub_level, sub_level + 1, dtype=np.float64)
            symbols_64 = indices * step
            symbols_64 = np.clip(symbols_64, info.min, info.max)
            symbols = symbols_64.astype( self.data_type)
            center_symbol = symbols[sub_level]
            result_symbols = np.concatenate((symbols[:sub_level], symbols[sub_level + 1:]))
            return result_symbols.tolist(), float(center_symbol)

    def __init__(self, fsk_level: int, full_vs_symbol_samples_count: int, value_symbol_samples_count: int,
                 dynamic_fsk: str = "false", dynamic_fsk_min: int = 0, dynamic_fsk_max: int = 0,
                 dynamic_smoothing: str = "false", dynamic_smoothing_min: float = 1.0, dynamic_smoothing_max: float = 2.0,
                 errors_mode: str = "ignore", smoothing: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.full_vs_symbol_samples_count = full_vs_symbol_samples_count
        self.value_symbol_samples_count = value_symbol_samples_count
        self.sync_symbol_samples_count = full_vs_symbol_samples_count - value_symbol_samples_count
        self.dynamic_fsk: bool = dynamic_fsk.lower() == 'true'
        if self.dynamic_fsk:
            if not all([l in self.supported_fsk_levels for l in (dynamic_fsk_min, dynamic_fsk_max)]):
                raise ValueError(f"Unsupported dynamic FSK levels {dynamic_fsk_min}-{dynamic_fsk_max}!")
            if dynamic_fsk_max < dynamic_fsk_min:
                raise ValueError(f"Max dynamic FSK level < min dynamic FSK level: {dynamic_fsk_max} < {dynamic_fsk_min}!")
        self.dynamic_fsk_levels: List[int] = list(self.supported_fsk_levels[self.supported_fsk_levels.index(dynamic_fsk_min):self.supported_fsk_levels.index(dynamic_fsk_max)+1])
        if len(self.dynamic_fsk_levels) <= 1:
            raise ValueError(f"Count of dynamic FSK levels must be bigger then 1, not {len(self.dynamic_fsk_levels)}!")
        self.errors_mode = "skip" if errors_mode not in self._errors_modes else errors_mode
        self.sync_char_in_str = '█'
        self.error_char_in_str = '❌'
        self.dynamic_smoothing: bool = dynamic_smoothing.lower() == 'true'
        if self.dynamic_smoothing:
            if dynamic_smoothing_max < dynamic_smoothing_min:
                raise ValueError(f"Max dynamic smoothing coff < min dynamic smoothing coff: {dynamic_smoothing_max} < {dynamic_smoothing_min}!")
            if (dynamic_smoothing_max - dynamic_smoothing_min) > self.max_dynamic_smoothing_diff:
                raise ValueError(f"Dynamic smoothing diff must be smaller then {self.max_dynamic_smoothing_diff}, but not: {dynamic_smoothing_max - dynamic_smoothing_min}")
            self.dynamic_smoothing_min = dynamic_smoothing_min
            self.dynamic_smoothing_max = dynamic_smoothing_max
        self.fsk_level = 2
        self.smoothing = smoothing
        if self.dynamic_fsk:
            self.set_random_smoothing_and_fsk_level()
        else:
            self.set_fsk_level(fsk_level, smoothing)
        self.logger.debug(f"Initiated WavAudio {self.to_json()}")

    def set_fsk_level(self, new_fsk_level: int, new_smoothing: float = 1.0) -> None:
        if new_fsk_level not in self.supported_fsk_levels:
            raise ValueError(f"FSK level must be in {self.supported_fsk_levels}, but not {new_fsk_level}!")
        self.fsk_level = new_fsk_level
        self.smoothing = new_smoothing
        self.value_symbols, self.sync_symbol = self._create_value_symbols()
        self.frame_full_symbols_count = self._int_div(self.samples_rate, self.full_vs_symbol_samples_count, "samples rate", "samples count for full symbol")
        self.bits_in_value_symbol = int(math.log2(self.fsk_level))
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

    def fsk_frame_bytes_to_str(self, frame: bytes, add_sync_symbols: bool = False, vs_mode: bool = False) -> str:
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

    def set_random_smoothing_and_fsk_level(self) -> Tuple[int, float]:
        new_level = random.choice([lv for lv in self.dynamic_fsk_levels if lv != self.fsk_level]) if self.dynamic_fsk else self.fsk_level
        new_smoothing = round(random.uniform(self.dynamic_smoothing_min, self.dynamic_smoothing_max), 2) if self.dynamic_smoothing else self.smoothing
        if new_level == self.fsk_level and new_smoothing == self.smoothing:
            raise ArithmeticError("The operation is pointless. The previous N-FSK values are the same as the new ones!")
        self.set_fsk_level(new_level, new_smoothing)
        return (new_level, new_smoothing)

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "fsk_level": self.fsk_level, "dynamic_fsk_levels": self.dynamic_fsk_levels if self.dynamic_fsk else (0,0),
                   "smoothing": self.smoothing, "dynamic_smoothing": (self.dynamic_smoothing_min, self.dynamic_smoothing_max) if self.dynamic_smoothing else (0,0),
                   "full_vs_symbol_samples_count": self.full_vs_symbol_samples_count, "value_symbol_samples_count": self.value_symbol_samples_count,
                   "sync_symbol_samples_count": self.sync_symbol_samples_count, "frame_full_symbols_count": self.frame_full_symbols_count, "bits_in_value_symbol": self.bits_in_value_symbol, "real_speed_bytes_per_sec": self.real_speed_bytes_per_sec,
                   "sync_char_in_str": self.sync_char_in_str, "error_char_in_str": self.error_char_in_str, "value_symbols_seq_length": self.value_symbols_seq_length, "sync_symbols_seq_length": self.sync_symbols_seq_length,
                   "result_str_index_shift": self.result_str_index_shift, "value_symbol_duration_sec": self.value_symbol_duration_sec, "sync_symbol_duration_sec": self.sync_symbol_duration_sec,
                   "full_symbol_duration_sec": self.full_symbol_duration_sec, "base256_charset": self._BASE256_CHARSET, "value_symbols": self.value_symbols, "sync_symbol": self.sync_symbol,
                   "supported_fsk_levels": self.supported_fsk_levels, "supported_data_types": self.supported_data_types, "errors_mode": self.errors_mode}
