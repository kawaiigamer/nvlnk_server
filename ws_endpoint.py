import argparse
import logging
import threading
import traceback
import uuid
from dataclasses import dataclass
from datetime import timedelta, datetime
from enum import Enum

from functools import wraps
from typing import Dict, Union, List, Optional

from flask import Flask, request, Response, render_template, session

from server_description import get_wav_params, get_aes_params, get_wav_fsk_params, get_system_info, get_private_data
from server_logging import DefaultLogger, EndpointLogger
from server_meshtastic import meshtastic_get_nodes, meshtastic_save_dumped_nodes, meshtastic_json_format_dumped_nodes, \
    MeshtasticKnownNode, meshtastic_send_message
from server_private import EndpointPrivateData
from server_storage import StreamsStorage
from server_streaming import AsyncAudioStream, AsyncAudioStreamBase, WavAudio, WavAudioNFSK, AESCrypterBase
from server_tox import ToxClientThread


class HTTPCodes(Enum):
    OK = 200
    NO_CONTENT = 204
    UNAUTHORIZED = 401
    NOT_ACCEPTABLE = 406
    CONTENT_TOO_LARGE = 413
    MISDIRECTED_REQUEST = 421
    CONFLICT = 409
    INTERNAL_SERVER_ERROR = 500
    SERVICE_UNAVAILABLE = 503



@dataclass
class EndpointPrivateHandlerObject:
    streams_storage: StreamsStorage
    private_data: EndpointPrivateData
    logger: EndpointLogger
    tox_thread: Optional[ToxClientThread] = None


def init_endpoint_private_handle_object() -> EndpointPrivateHandlerObject:
    __private_data = get_private_data()
    __logger = DefaultLogger(__private_data)
    handler: EndpointPrivateHandlerObject = EndpointPrivateHandlerObject(streams_storage=StreamsStorage(
        clear_interval=timedelta(seconds=__private_data.default_session_lifetime_seconds),
        stream_lifetime=timedelta(seconds=__private_data.default_session_lifetime_seconds),
        logger=__logger),
        private_data=get_private_data(),
        logger=__logger)
    if __private_data.tox_id and __private_data.tox_profile_name and __private_data.tox_profile_password:
        try:
            handler.tox_thread = ToxClientThread(__logger, __private_data.tox_profile_name, __private_data.tox_profile_password)
            handler.tox_thread.run()
        except Exception as exp:
            handler.logger.error(f"Exception while initialization tox thread {exp}")
    return handler

handler: EndpointPrivateHandlerObject = init_endpoint_private_handle_object()
app = Flask(__name__)
app.permanent_session_lifetime = timedelta(seconds=handler.private_data.default_session_lifetime_seconds)
app.secret_key = uuid.uuid4().hex


def internal_server_error_throwable(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as ve:
            handler.logger.exception("ValueError exception")
            tb = ve.__traceback__
            _, line_num, func_name, _ = traceback.extract_tb(tb)[-1]
            while tb.tb_next:
                tb = tb.tb_next
            if instance := tb.tb_frame.f_locals.get('self'):
                class_name = instance.__class__.__name__
            else:
                class_name = tb.tb_frame.f_locals.get('cls').__name__
            return {"error": f"Internal Server Error! [{class_name}::{line_num}:{func_name}] {str(ve)}"}, HTTPCodes.INTERNAL_SERVER_ERROR.value
    return decorated_function


def authentication_required(f):
    @wraps(f)
    def authentication_function(*args, **kwargs):
        access_key = request.cookies.get("access_key")
        if access_key == handler.private_data.access_key:
            return f(*args, **kwargs)
        else:
            handler.logger.exception(f"Unauthorized client with access_key: {access_key}")
            return "access_key is not valid", HTTPCodes.UNAUTHORIZED.value
    return authentication_function


def internal_stream_session_handler(f):
    @wraps(f)
    def decorated_stream_function(*args, **kwargs):
        handler.logger.debug(f"request.range {request.range}, session.get('stream_uuid') = {session.get('stream_uuid')}") #TODO: request.range bytes=3528044-, session.get('stream_uuid') = None
        if session_uuid := session.get('stream_uuid'):
            if storaged_stream := handler.streams_storage.get_stream(session_uuid):
                new_stream: AsyncAudioStream = f(stream=storaged_stream, *args, **kwargs)
                handler.logger.debug(f"Found in storage ={storaged_stream.stream_uuid}, new_stream {new_stream.stream_uuid}")
            else:
                s = AsyncAudioStreamBase(handler.logger, uuid.uuid4().hex)
                new_stream: AsyncAudioStream = f(stream=s, *args, **kwargs)
                handler.logger.debug(f"Found uuid in session but not stream in storage, StreamBase: {s.stream_uuid} new_stream {new_stream.stream_uuid}")
        else:
            s = AsyncAudioStreamBase(handler.logger,  uuid.uuid4().hex)
            new_stream: AsyncAudioStream = f(stream=s, *args, **kwargs)
            handler.logger.debug(f"Not found uuid in session StreamBase: {s.stream_uuid}, new_stream {new_stream.stream_uuid}")
        handler.streams_storage.add_stream(new_stream.stream_uuid, new_stream)
        session['stream_uuid'] = new_stream.stream_uuid
        session.modified = True
        return new_stream.start()
    return decorated_stream_function


@app.route('/favicon.ico')
def favicon():
    return '', HTTPCodes.NO_CONTENT.value


@app.route("/")
#@authentication_required
def main_page():
    return Response(get_system_info(), mimetype='application/json')

# -------------------- wav --------------------

@app.route('/wav/random/stream')
@internal_server_error_throwable
@internal_stream_session_handler
#@authentication_required
def wav_random_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudio(**get_wav_params(request.args)))


@app.route('/wav/random/N-FSK/stream')
@internal_server_error_throwable
@internal_stream_session_handler
#@authentication_required
def wav_random_nfsk_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger), logger=handler.logger)


@app.route('/wav/random/aes256/stream')
@internal_server_error_throwable
@internal_stream_session_handler
#@authentication_required
def wav_random_aes256_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger, crypter=AESCrypterBase.from_config(get_aes_params(request.args))), logger=handler.logger)



@app.route('/wav/random/aes256_N-FSK/stream')
@internal_server_error_throwable
#@authentication_required
def wav_random_aes256_nfsk_stream():
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger), logger=handler.logger, crypter=AESCrypterBase.from_config(get_aes_params(request.args))).start()


app.config['LAST_PLAIN_TEXT_STR'] = ''
@app.route('/wav/text/aes256_N-FSK/crypter', methods=['GET', 'POST'])
@internal_server_error_throwable
#@authentication_required
def wav_text_aes256_nfsk_crypter():
    aes_params = get_aes_params(request.args)
    if request.method == 'POST':
        aes_params["text"] = request.form.get('text', aes_params.get("text"))
        app.config['LAST_PLAIN_TEXT_STR'] = aes_params["text"]
    else:
        if app.config['LAST_PLAIN_TEXT_STR']:
            aes_params["text"] = app.config['LAST_PLAIN_TEXT_STR']
            app.config['LAST_PLAIN_TEXT_STR'] = ''
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger), crypter=AESCrypterBase.from_config(aes_params), logger=handler.logger).start()


@app.route('/wav/text/aes256_N-FSK/crypter/form', methods=['GET'])
#@authentication_required
def wav_text_aes256_nfsk_crypter_form():
    return render_template('input_wav_text.html')


@app.route('/wav/text/aes256_N-FSK/decrypter', methods=["GET", 'POST'])
@internal_server_error_throwable
#@authentication_required
def wav_text_aes256_nfsk_decrypter():
    if request.method == 'GET':
        return render_template('input_wav_file.html')
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger), crypter=AESCrypterBase.from_config(get_aes_params(request.args)), logger=handler.logger).wav_aes_nfsk_decrypt(request.data), 200

# -------------------- wav ---------------------------

# -------------------- meshtastic --------------------

@app.route('/meshtastic/get_nodes', methods=['GET'])
#@authentication_required
def meshtastic_get_nodes_endpoint():
    available_nodes_count: int = len(handler.private_data.meshtastic_nodes)
    current_node = request.args.get("ID")
    if available_nodes_count > 1 and not current_node:
        return "Node ID is not set", HTTPCodes.CONFLICT.value
    result: List[MeshtasticKnownNode] = meshtastic_get_nodes(logger=handler.logger, short_name=current_node, count=int(request.args.get("count", 250)))
    if request.args.get("save") == "true":
        meshtastic_save_dumped_nodes(result)
    return Response(meshtastic_json_format_dumped_nodes(result), mimetype='application/json')


@app.route('/meshtastic/send_message', methods=['GET'])
#@authentication_required
def meshtastic_send_message_endpoint():
    MAX_TEXT_LENGTH = 92
    current_node = request.args.get("ID")
    if text := request.args.get("text"):
        if len(text) > MAX_TEXT_LENGTH:
            return f"Text message too large: {len(text)} > {MAX_TEXT_LENGTH}!", HTTPCodes.CONTENT_TOO_LARGE.value
        try:
            meshtastic_send_message(handler.logger, text, int(request.args.get("ch", 0)), int(request.args.get("to", -1)), short_name=current_node)
            return "", HTTPCodes.OK.value
        except ValueError:
            msg = f"Channel index: {request.args.get("ch")} and destination id: {request.args.get("to")} must be integers!"
            handler.logger.exception(msg)
            return msg, HTTPCodes.NOT_ACCEPTABLE.value
    else:
        return "Message text is not set", HTTPCodes.MISDIRECTED_REQUEST.value


# get_msgs?count last
# get_metrics?last_hours= (def=24)

# -------------------- meshtastic --------------------

# -------------------- tox ---------------------------
@app.route('/tox/send_message', methods=['GET'])
#@authentication_required
def tox_send_message_endpoint():
    if not handler.tox_thread or not handler.tox_thread.is_running():
        return "Tox service is not acceptable", HTTPCodes.SERVICE_UNAVAILABLE.value
    text = request.args.get("text")
    chat_id = request.args.get("chat_id")
    if not text or not chat_id:
        return f"Text: {text}, or chat ID: {chat_id} is invalid or not set", HTTPCodes.NO_CONTENT.value
    try:
        handler.tox_thread.send_message_safely(chat_id, text)
        return "Sending message command queued", HTTPCodes.OK.value
    except Exception as exp:
        return f"Exception while sending tox message: Text: {text}, chat ID: {chat_id}, Exception: {exp}", HTTPCodes.INTERNAL_SERVER_ERROR.value

# -------------------- tox ---------------------------

# -------------------- MAIN --------------------

def main() -> None:
    # --- Parse args
    parser = argparse.ArgumentParser(description="ws-http-endpoint")
    parser.add_argument('-k', '--key', type=str, default="", help='Key for decrypting private data (AES-256 CBC)')
    parser.add_argument('-p', '--port', type=int, default=60600, help='port(default=%(default)s)')
    parser.add_argument("-d", "--debug", default=True, help="enable debug mode(default=%(default)s)")
    args = parser.parse_args()

    # --- Starting endpoint
    handler.logger.debug(f"Endpoint version: {handler.private_data.version}, release type: {handler.private_data.release_type} started!")
    app.run(host='0.0.0.0', port=args.port, debug=args.debug, use_reloader=True)


if __name__ == '__main__':
    main()


