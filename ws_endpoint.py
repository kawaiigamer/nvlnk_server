import argparse
import os
import traceback
import uuid
from dataclasses import dataclass
from datetime import timedelta, datetime
from enum import Enum

from functools import wraps
from typing import Dict, Union, List, Optional

from flask import Flask, request, Response, render_template, session

from server_description import get_wav_params, get_aes_params, get_wav_fsk_params, get_system_info, get_private_data
from server_logging import DefaultLogger, EndpointLogger, ExtendedLevelsLogger
from server_meshtastic import MeshtasticWireHandleThread
from server_private import EndpointPrivateConfig
from server_storage import StreamsStorage
from server_streaming import AsyncAudioStream, AsyncAudioStreamBase, WavAudio, WavAudioNFSK, AESCrypterBase
from server_tox import ToxClientThread


class HTTPCodes(Enum):
    OK = 200
    NO_CONTENT = 204
    UNAUTHORIZED = 401
    NOT_FOUND = 404
    NOT_ACCEPTABLE = 406
    CONTENT_TOO_LARGE = 413
    MISDIRECTED_REQUEST = 421
    CONFLICT = 409
    INTERNAL_SERVER_ERROR = 500
    SERVICE_UNAVAILABLE = 503


@dataclass
class EndpointPrivateHandlerObject:
    streams_storage: StreamsStorage
    private_data: EndpointPrivateConfig
    logger: EndpointLogger
    tox_instance: ToxClientThread = None
    meshtastic_instances: Dict[str, MeshtasticWireHandleThread] = None

def init_endpoint_private_handle_object() -> EndpointPrivateHandlerObject:
    __private_data = get_private_data()
    __logger = ExtendedLevelsLogger(__private_data)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        __logger.visualize()
    handler: EndpointPrivateHandlerObject = EndpointPrivateHandlerObject(
        streams_storage=StreamsStorage(
        clear_interval=timedelta(seconds=__private_data.http_session_lifetime),
        stream_lifetime=timedelta(seconds=__private_data.http_session_lifetime),
        logger=__logger),
        private_data=get_private_data(),
        logger=__logger)

    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":  # TODO: remove after debug

        if __private_data.tox_config:
            try:
                handler.tox_instance = ToxClientThread(__logger, "tox", __private_data.tox_config)
                handler.tox_instance.start()
                #handler.tox_instance = IOQueuedThread(ToxClientThread(__logger, __private_data.tox_config),
                               #LimitedTypedQueue[InternalQueuedItem](__logger, max_size=handler.private_data.tox_config.queue_max_size, name="Tox"))
                # handler.tox_instance_cmd_queue = queue.Queue()
                # handler.tox_instance = ToxClientThread(__logger, __private_data.tox_config)
                # handler.tox_instance = threading.Thread(target=handler.tox_instance, daemon=True, args=(handler.tox_instance_cmd_queue,))
                #
            except Exception as exp:
                handler.logger.exception(f"Exception while initialization tox instance thread: {exp}")

        if __private_data.meshtastic_nodes:
                handler.meshtastic_instances = dict()
                for node in __private_data.meshtastic_nodes.values():
                    try: #LimitedTypedQueue[InternalQueuedItem](logger, max_size=config.queue_max_size, name=f"meshtastic_{config.short_name}")
                        handler.meshtastic_instances[node.short_name] = MeshtasticWireHandleThread(handler.logger, node)
                        #handler.meshtastic_instances[node.short_name] = threading.Thread(target=handler.meshtastic_instances[node.short_name], daemon=True)
                        handler.meshtastic_instances[node.short_name].start()
                        #handler.meshtastic_instances[node.short_name] = __init_thread_instance(MeshtasticWireHandleThread(handler.logger, node))
                    except Exception as exp:
                        handler.logger.exception(f"Exception while initialization meshtastic instance: {node.short_name}, thread: {exp}")

    app.permanent_session_lifetime = timedelta(seconds=handler.private_data.http_session_lifetime)
    return handler


handler: EndpointPrivateHandlerObject
app = Flask(__name__)
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
        # access_key = request.cookies.get("access_key")
        # if access_key == handler.private_data.access_key:
        #     return f(*args, **kwargs)
        # else:
        #     handler.logger.exception(f"Unauthorized client with access_key: {access_key}")
        #     return "access_key is not valid", HTTPCodes.UNAUTHORIZED.value
        return f(*args, **kwargs)
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
@authentication_required
def main_page():
    return Response(get_system_info(), mimetype='application/json')

# -------------------- wav --------------------

@app.route('/wav/random/stream')
@internal_server_error_throwable
@internal_stream_session_handler
@authentication_required
def wav_random_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudio(**get_wav_params(request.args)))


@app.route('/wav/random/N-FSK/stream')
@internal_server_error_throwable
@internal_stream_session_handler
@authentication_required
def wav_random_nfsk_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger), logger=handler.logger)


@app.route('/wav/random/aes256/stream')
@internal_server_error_throwable
@internal_stream_session_handler
@authentication_required
def wav_random_aes256_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger, crypter=AESCrypterBase.from_config(get_aes_params(request.args))), logger=handler.logger)

@app.route('/wav/random/aes256_N-FSK/stream')
@internal_server_error_throwable
@authentication_required
def wav_random_aes256_nfsk_stream():
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger), logger=handler.logger, crypter=AESCrypterBase.from_config(get_aes_params(request.args))).start()


app.config['LAST_PLAIN_TEXT_STR'] = ''
@app.route('/wav/text/aes256_N-FSK/crypter', methods=['GET', 'POST'])
@internal_server_error_throwable
@authentication_required
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
@authentication_required
def wav_text_aes256_nfsk_crypter_form():
    return render_template('input_wav_text.html')


@app.route('/wav/text/aes256_N-FSK/decrypter', methods=["GET", 'POST'])
@internal_server_error_throwable
@authentication_required
def wav_text_aes256_nfsk_decrypter():
    if request.method == 'GET':
        return render_template('input_wav_file.html')
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args), logger=handler.logger), crypter=AESCrypterBase.from_config(get_aes_params(request.args)), logger=handler.logger).wav_aes_nfsk_decrypt(request.data), 200

# -------------------- wav ---------------------------
# -------------------- tox ---------------------------

@app.route('/tox/send_message', methods=['GET'])
@internal_server_error_throwable
@authentication_required
def tox_send_message_endpoint():
    if not handler.tox_instance or not handler.tox_instance.is_running:
        return "Tox service is not acceptable", HTTPCodes.SERVICE_UNAVAILABLE.value
    text = request.args.get("text")
    chat_id: int = int(request.args.get("chat_id"))
    if not text or not chat_id:
        return f"Text: {text}, or chat id: {chat_id} is invalid or not set", HTTPCodes.NO_CONTENT.value
    try:
        handler.tox_instance.send_message_safely(chat_id, text)
        return "Sending message command queued", HTTPCodes.OK.value
    except Exception as exp:
        return f"Exception while sending tox_data message: text: {text}, chat id: {chat_id}, Exception: {exp}", HTTPCodes.INTERNAL_SERVER_ERROR.value


@app.route('/tox/get_messages', methods=['GET'])
@internal_server_error_throwable
@authentication_required
def tox_get_messages_endpoint():
    if not handler.tox_instance or not handler.tox_instance.is_running:
        return "Tox client is not running", HTTPCodes.SERVICE_UNAVAILABLE.value
    try:
        count: int = int(request.args.get("count", handler.private_data.tox_config.input_queue_max_size))
    except ValueError:
        return f"Count param is invalid: {request.args.get("count")}", HTTPCodes.NOT_ACCEPTABLE.value
    return Response([item.to_json() for item in handler.tox_instance.output_queue.get_batch(count)], mimetype='application/json')

# -------------------- tox ---------------------------
# -------------------- meshtastic --------------------

@app.route('/meshtastic/get_nodes', methods=['GET'])
@authentication_required
def meshtastic_get_nodes_endpoint():
    available_nodes_count: int = len(handler.private_data.meshtastic_nodes)
    current_node = request.args.get("ID")
    if available_nodes_count > 1 and not current_node:
        return "Node ID is not set", HTTPCodes.CONFLICT.value
    if node := handler.meshtastic_instances.get(current_node):
        result = node.get_all_known_nodes_via_usb()
        if request.args.get("save") == "true":
            node.save_dumped_nodes(result)
        response: str = node._json_format_dumped_nodes(result)
        handler.logger.dump(f"Nodes summary:\n{response}")
        return Response(response, mimetype='application/json')
    return f"Node with ID {current_node} not found!", HTTPCodes.NOT_FOUND.value


@app.route('/meshtastic/send_message', methods=['GET'])
@authentication_required
def meshtastic_send_message_endpoint():
    MAX_TEXT_LENGTH = 160
    current_node = request.args.get("ID")
    if node := handler.meshtastic_instances.get(current_node):
        if not node.is_running:
            return f"Node with ID {current_node} is not running", HTTPCodes.SERVICE_UNAVAILABLE.value
        if text := request.args.get("text"):
            if len(text) > MAX_TEXT_LENGTH:
                return f"Text message too large: {len(text)} > {MAX_TEXT_LENGTH}!", HTTPCodes.CONTENT_TOO_LARGE.value
            try:
                node.send_message(text, int(request.args.get("ch", 0)), int(request.args.get("to", -1)))
                return "", HTTPCodes.OK.value
            except ValueError:
                msg = f"Channel index: {request.args.get("ch")} and destination id: {request.args.get("to")} must be integers!"
            except Exception as e:
                msg = f"Exception while sending message: {e}"
            handler.logger.exception(msg)
            return msg, HTTPCodes.NOT_ACCEPTABLE.value
    else:
        return "Message text is not set", HTTPCodes.MISDIRECTED_REQUEST.value


@app.route('/meshtastic/get_messages', methods=['GET'])
@internal_server_error_throwable
@authentication_required
def meshtastic_get_messages_endpoint():
    current_node = request.args.get("ID")
    if node := handler.meshtastic_instances.get(current_node):
        if not node.is_running:
            return f"Node with ID {current_node} is not running", HTTPCodes.SERVICE_UNAVAILABLE.value
        try:
            count: int = int(request.args.get("count", node.i))
        except ValueError:
            return f"Count param is invalid: {request.args.get("count")}", HTTPCodes.NOT_ACCEPTABLE.value
        return Response([item.to_json() for item in node._output_queue.get_batch(count)],
                        mimetype='application/json')
    return f"Node with ID {current_node} not found", HTTPCodes.NOT_FOUND.value

# -------------------- meshtastic --------------------

# -------------------- MAIN --------------------


def main() -> None:
    handler = init_endpoint_private_handle_object()
    # --- Parse args
    parser = argparse.ArgumentParser(description="ws-http-endpoint")
    parser.add_argument('-k', '--key', type=str, default="", help='Key for decrypting private data (AES-256 CBC)')
    parser.add_argument('-p', '--port', type=int, default=60600, help='port(default=%(default)s)')
    parser.add_argument("-d", "--debug", default=True, help="enable debug mode(default=%(default)s)")
    args = parser.parse_args()

    # --- Starting endpoint
    handler.logger.system(f"Endpoint version: {handler.private_data.version.__str__()}, release type: {handler.private_data.release_type} started!")
    app.run(host='0.0.0.0', port=args.port, debug=args.debug, use_reloader=True)


if __name__ == '__main__':
    main()


