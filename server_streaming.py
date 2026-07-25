import asyncio
import datetime
import uuid
import json
import math
import os
import random
from datetime import datetime, timedelta
import struct
import io
import wave
from itertools import count
from typing import Optional, Generator, AsyncGenerator, Union, List, Iterable, Tuple, Type, Any, Dict

import numpy as np
from flask import Response

from server_audio import WavAudio, WavAudioNFSK
from server_cryptography import AESCrypterBase
from server_logging import SimpleDebugOnlyLogger
from server_description import _TIME_FMT


class AsyncAudioStreamBase:
    def __init__(self, stream_uuid: str = "", **kwargs):
        self.stream_uuid: str = stream_uuid
        self.created_at: datetime = datetime.now()

    def to_json(self) -> Dict[str, Any]:
        return {"stream_uuid": self.stream_uuid, "created_at": self.created_at}

    def is_deprecated(self, secs: timedelta) -> bool:
        return (datetime.now() - self.created_at) > secs


class AsyncAudioStream(AsyncAudioStreamBase):
    def __init__(self, wav: Union[WavAudio, WavAudioNFSK], crypter: Optional[AESCrypterBase] = None, req_range = None,  debug: bool=True, **kwargs):
        super().__init__(**kwargs)
        self.wav: Union[WavAudio, WavAudioNFSK] = wav
        self.frames_delay = 1
        self.crypter = crypter
        self.expected_frames_count = 0
        self._req_range = req_range
        self.logger = SimpleDebugOnlyLogger(self.stream_uuid, io=print if debug else None)
        self.frame_body_length_without_aes_payload = self.wav.frame_length
        self.sgw = None
        self.sample_gen = None
        self.asg = None

    @staticmethod
    def from_base(base: AsyncAudioStreamBase, **kwargs):
        a =AsyncAudioStream(stream_uuid=base.stream_uuid, created_at=base.created_at, **kwargs)
        print("FROM BASE",a.to_json())
        return a

    def _log_frame(self, frame_no: int, bits: np.ndarray, fsk_frame: np.ndarray, include_sync_symbols: bool = True) -> None:
        out_io = self.logger.stream_msgs_block_gen(frame_no)
        if not next(out_io):
            return
        out_io.send((f"Received {bits.size} bits for next frame(charset_len=2): ", self.wav.bits_array_to_str(bits, False)))
        out_io.send((f"Received {bits.size} bits for next frame(charset_len={self.wav.fsk_level}): ", self.wav.bits_array_to_str(bits, False)))
        out_io.send((f"Yielding {fsk_frame.nbytes} bytes for next FSK frame(without sync symbols)(charset_len=2): ", self.wav.fsk_frame_to_str(fsk_frame, False)))
        out_io.send((f"Yielding {fsk_frame.nbytes} bytes for next FSK frame(without sync symbols)(charset_len={self.wav.fsk_level}): ", self.wav.fsk_frame_to_str(fsk_frame, False, True)))
        if include_sync_symbols:
            out_io.send((f"Yielding {fsk_frame.nbytes} bytes for next FSK frame(without sync symbols)(charset_len=2): ", self.wav.fsk_frame_to_str(fsk_frame, True)))
            out_io.send((f"Yielding {fsk_frame.nbytes} bytes for next FSK frame(without sync symbols)(charset_len={self.wav.fsk_level}): ",  self.wav.fsk_frame_to_str(fsk_frame, True, True)))
        out_io.close()

    def _init_generators(self) -> None:
        if self.crypter:
            self.frame_body_length_without_aes_payload = self.wav.frame_length - self.crypter.additional_payload_length
            if self.frame_body_length_without_aes_payload <= 0:
                raise ValueError(f"Sample body length: {self.frame_body_length_without_aes_payload} must be bigger then: {self.crypter.additional_payload_length}")
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
                self.logger.msg_lazy(lambda: f"Padding last yielding bits seq with {bits_per_iteration - len(sub_array)} bits: {pad_bit}")
                padded_array = np.pad(
                    sub_array,
                    pad_width=(0, bits_per_iteration - len(sub_array)),
                    mode='constant',
                    constant_values=pad_bit
                )
                counter += bits_per_iteration
                yield padded_array

    def _text_aes_crypted_fsk_frames_gen(self) -> Generator[bytes, None, None]:   #TODO
        self.logger.msg_lazy(lambda: f"Received Plain Text: {self.logger.cut_seq_with_prefix(self.crypter.text, 32)}, Using {self.crypter.__class__.__name__},  Additional AES bytes count: {self.crypter.additional_payload_length}...")
        encrypted_text_bytes: bytes = self.crypter.encrypt(self.crypter.text)
        encrypted_text_bits: np.ndarray = self.wav.bytes_to_bits_array(encrypted_text_bytes)
        bits_as_full_symbols_in_frame: int = self.wav.frame_full_symbols_count*self.wav.bits_in_value_symbol
        self.expected_frames_count = math.ceil(len(encrypted_text_bits) / self.wav.frame_full_symbols_count / self.wav.bits_in_value_symbol)
        self.logger.msg_lazy(lambda: f"AES crypted bytes: {self.logger.cut_seq_with_prefix(encrypted_text_bytes)}, AES crypted bits: {encrypted_text_bits}, "
                        f"Bits in frame(as full symbols): {bits_as_full_symbols_in_frame}, Expected frames count: {self.expected_frames_count}")
        yield
        for i, padded_bits_per_frame in enumerate(self._padded_bits_gen(encrypted_text_bits, bits_as_full_symbols_in_frame), 1):
            fsk_frame: np.ndarray = self.wav.create_fsk_frame(padded_bits_per_frame)
            self._log_frame(i, padded_bits_per_frame, fsk_frame)
            yield fsk_frame.tobytes()

    def _random_frames_gen(self) -> Generator[bytes, None, None]:
        while True:
            yield self.wav.create_random_frame()

    def _random_aes_crypted_frames_gen(self, fixed_random_bytes_length: int = 0) -> Generator[bytes, None, None]:
        if not fixed_random_bytes_length:
            fixed_random_bytes_length = self.frame_body_length_without_aes_payload
        while True:
            yield self.crypter.encrypt(random.randbytes(fixed_random_bytes_length))

    def _random_fsk_frames_gen(self) -> Generator[bytes, None, None]:
        for i in count(start=1):
            if self.wav.dynamic_fsk:
                l, s = self.wav.set_random_smoothing_and_fsk_level()
                self.logger.msg(f"New FSK level: {l}, New smoothing coff: {s}")
                self.logger.msg_lazy(lambda: f"[sec={i}] Fsk level changed, new N-FSK config: {self.wav.to_json()}")
            bits: np.ndarray = self.wav.create_random_bits_array(self.wav.frame_full_symbols_count*self.wav.bits_in_value_symbol)
            fsk_frame: np.ndarray = self.wav.create_fsk_frame(bits)
            self._log_frame(i, bits, fsk_frame, include_sync_symbols=False)
            yield fsk_frame.tobytes()

    def _random_aes_fsk_frames_gen(self) -> Generator[bytes, None, None]: #TODO
        aes_crypted_frames_gen = self._random_aes_crypted_frames_gen()
        sec = 1
        while True:
            for bits in self._padded_bits_gen(self.wav.bytes_to_bits_array(next(aes_crypted_frames_gen)), self.wav.frame_full_symbols_count * self.wav.bits_in_value_symbol):
                fsk_frame: np.ndarray = self.wav.create_fsk_frame(bits)
                self._log_frame(sec, bits, fsk_frame, include_sync_symbols=True)
                yield fsk_frame.tobytes()
                sec += 1

    def wav_aes_nfsk_decrypt(self, data: bytes) -> Optional[str]:
        PADDING_DETECTION_SAME_BITS_COUNT = 5

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
            self.logger.msg_lazy(lambda: f'Wav header parsed params: { {"channels": channels, "channel_byte_length": channel_byte_length, "channel_bit_depth": channel_bit_depth,
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
                    continue
                else:
                    self.logger.msg(f"{_message}, ignoring current frame!")

            frame_bits_in_value_symbol = int(math.log2(len(frame_value_symbols)))
            self.logger.msg_lazy(lambda: f'[Frame={frame_counter}] N-FSK params: { {"fsk_level": frame_fsk_level, "bits_in_value_symbol": frame_bits_in_value_symbol,
                                                                                "sync_symbol": frame_sync_symbol, "value_symbols": frame_value_symbols} }')

            # Extracting only value symbols sequence and converting its to bits
            frame_symbols_seq: np.ndarray = frame[np.concatenate(([True], frame[1:] != frame[:-1]))]
            self.logger.msg(f"[Frame={frame_counter}] All detected symbols sequence length: {frame_symbols_seq.size}")
            if frame_sync_symbol is not None:
                frame_symbols_seq = frame_symbols_seq[frame_symbols_seq != frame_sync_symbol]
            self.logger.msg(f"[Frame={frame_counter}] All detected value symbols sequence length: {frame_symbols_seq.size}")
            frame_bits_from_value_symbols: List[np.ndarray] = [np.fromiter(np.binary_repr(frame_value_symbols.index(s), width=frame_bits_in_value_symbol), dtype=int) for s in frame_symbols_seq]
            bits_summary += frame_bits_from_value_symbols

        # Concatenating all bit sequences from all frames
        all_bits: np.ndarray = np.concatenate(bits_summary)
        self.logger.msg(f"Concatenated from all frames bits sequence length: {all_bits.size}")

        # Detecting bits padding and all unpadding bits sequence
        last_bit = all_bits[-1]
        unpadding_mask = (all_bits[::-1] == last_bit)
        same_bits_at_end = np.argmax(~unpadding_mask) if not np.all(unpadding_mask) else len(all_bits)
        if same_bits_at_end > PADDING_DETECTION_SAME_BITS_COUNT:
            self.logger.msg(f"Concatenated bits sequence looks like padded, last {same_bits_at_end} has same value: {last_bit}")
            all_bits = all_bits[:all_bits.size - same_bits_at_end]
            self.logger.msg(f"Unpadded concatenated bits sequence length: {all_bits.size}")

        # Converting bits sequence to bytes
        all_bytes: bytes = np.packbits(all_bits).tobytes()
        self.logger.msg(f"Concatenated bits sequence converted to bytes length: {len(all_bytes)}")
        s
        # Decrypting bytes plain text
        return self.crypter.decrypt(all_bytes)

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "expected_frames_count": self.expected_frames_count,
                "wav": self.wav.to_json(), "crypter": self.crypter.to_json() if self.crypter else {}}

    async def _async_stream_generator(self) -> AsyncGenerator[bytes, None]:
        self.logger.msg_lazy(lambda: f"Stream initiated with config: {self.to_json()}")
        #if str(self._req_range) == "bytes=0-":
        yield self.wav.create_wav_header(self.expected_frames_count)

        # if self._req_range is None:
        #     return


        #yield self.wav.create_wav_header(self.expected_frames_count)
        for i in count(start=1):
            try:
                yield next(self.sample_gen)
            except StopIteration:
                return
            if i == self.wav.duration:
                return
            await asyncio.sleep(self.frames_delay)

    def _sync_generator_wrapper(self) -> Generator[bytes, None, None]:
        loop = asyncio.new_event_loop()
        if self.asg:
            stream_gen = self.asg
        else:
            stream_gen = self._async_stream_generator()
            self.asg = stream_gen
        #self.asg = self._async_stream_generator()

        try:
            while True:
                try:
                    chunk = loop.run_until_complete(stream_gen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()


    def start(self, position: int = 0) -> Response:
        if self.wav.info_only:
            return Response(json.dumps(self.to_json(), indent=4, default=str, ensure_ascii=False), mimetype='application/json')
        self.logger.msg(f"_req_range: {self._req_range}")
        #if position == 0:
        self._init_generators()

        # if self._req_range is None:
        #      return Response(self.wav.create_wav_header(), mimetype='audio/wav')
        # if str(self._req_range) == "bytes=0-":
        self.sgw = self._sync_generator_wrapper()
        self.res = Response(self.sgw, mimetype='audio/wav') #=
        return self.res

    def continue_stream(self):
        #print(f"{self.to_json()}")
        return Response(self._sync_generator_wrapper(), mimetype='audio/wav') #=



