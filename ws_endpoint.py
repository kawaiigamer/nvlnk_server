import argparse
import json
import os
import threading
import traceback
import uuid
from enum import Enum

from functools import wraps
from typing import Union, Optional, Callable, List

from flask import Flask, request, Response, render_template, session

from src.core.server_core import EndpointPrivateHandlerObject, ServerCore, ServerCoreException
from src.core.description import global_get_wav_params, global_get_aes_params, global_get_wav_fsk_params, global_get_system_info
from src.log.loggers import EndpointLogger
from src.services.meshtastic import MeshtasticWireHandleThread, mesh_json_serial
from src.wav.streaming import AsyncAudioStream, AsyncAudioStreamBase, WavAudio, WavAudioNFSK, AESCrypterBase


# -- Globals

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

app = Flask(__name__)
app.secret_key = uuid.uuid4().hex
_COMPLEX_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _init_global_cache_at_boot(private_key: str):
    #print(f"init_global_cache_at_boot called, app.debug", app.debug, 'app.config.get("ENV")', app.config.get("ENV"), 'os.environ.get("WERKZEUG_RUN_MAIN")', os.environ.get("WERKZEUG_RUN_MAIN"))
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    global _COMPLEX_CACHE
    _COMPLEX_CACHE["core"] = ServerCore(private_key)
    _COMPLEX_CACHE["core"].start_core_threads()


def _get_core() -> Optional[ServerCore]:
    global _COMPLEX_CACHE, _CACHE_LOCK
    if len(_COMPLEX_CACHE) == 0:
        return None
    with _CACHE_LOCK:
        return _COMPLEX_CACHE.get("core")


def _get_core_handler() -> Optional[EndpointPrivateHandlerObject]:
    if core := _get_core():
        return core.get_handler()
    else:
        raise ServerCoreException("Core not initiated!")


def _get_core_logger() -> Optional[EndpointLogger]:
    if core := _get_core():
        return core.logger
    else:
        raise ServerCoreException("Core not initiated!")


def internal_server_error_throwable(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except (ValueError, ServerCoreException) as exp:
            _get_core_handler().logger.exception(f"{type(exp)} exception: {exp}")
            tb = exp.__traceback__
            _, line_num, func_name, _ = traceback.extract_tb(tb)[-1]
            while tb.tb_next:
                tb = tb.tb_next
            if instance := tb.tb_frame.f_locals.get('self'):
                class_name = instance.__class__.__name__
            else:
                class_name = tb.tb_frame.f_locals.get('cls').__name__
            return {"error": f"Internal Server Error! [{class_name}::{line_num}:{func_name}] {str(exp)}"}, HTTPCodes.INTERNAL_SERVER_ERROR.value
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
        handler = _get_core_handler()
        handler.logger.debug(f"request.range {request.range}, session.get('stream_uuid') = {session.get('stream_uuid')}")
        #TODO: request.range bytes=3528044-, session.get('stream_uuid') = None
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
    runtime = {"runtime": {}}
    if core := _get_core():
        runtime["runtime"]["working_instances"] = [wi.name for wi in core.get_working_instances(core.get_handler().meshtastic_instances, "meshtastic", pop=False)]
        if tox_thread := core.get_handler().tox_instance:
            if tox_thread.is_running:
                runtime["runtime"]["working_instances"].append(tox_thread.name)
    return Response(global_get_system_info(runtime), mimetype='application/json')

# -------------------- wav --------------------


@app.route('/wav/random/stream')
@internal_server_error_throwable
@internal_stream_session_handler
@authentication_required
def wav_random_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudio(**global_get_wav_params(request.args)))


@app.route('/wav/random/N-FSK/stream')
@internal_server_error_throwable
@internal_stream_session_handler
@authentication_required
def wav_random_nfsk_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    core_logger = _get_core_logger()
    return AsyncAudioStream.from_base(stream, wav=WavAudioNFSK(**global_get_wav_fsk_params(request.args), logger=core_logger), logger=core_logger)


@app.route('/wav/random/aes256/stream')
@internal_server_error_throwable
@internal_stream_session_handler
@authentication_required
def wav_random_aes256_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    core_logger = _get_core_logger()
    return AsyncAudioStream.from_base(stream, wav=WavAudioNFSK(**global_get_wav_fsk_params(request.args), logger=core_logger, crypter=AESCrypterBase.from_config(global_get_aes_params(request.args))), logger=core_logger)


@app.route('/wav/random/aes256_N-FSK/stream')
@internal_server_error_throwable
@authentication_required
def wav_random_aes256_nfsk_stream():
    core_logger = _get_core_logger()
    return AsyncAudioStream(wav=WavAudioNFSK(**global_get_wav_fsk_params(request.args), logger=core_logger), logger=core_logger, crypter=AESCrypterBase.from_config(global_get_aes_params(request.args))).start()


app.config['LAST_PLAIN_TEXT_STR'] = ''
@app.route('/wav/text/aes256_N-FSK/crypter', methods=['GET', 'POST'])
@internal_server_error_throwable
@authentication_required
def wav_text_aes256_nfsk_crypter():
    aes_params = global_get_aes_params(request.args)
    if request.method == 'POST':
        aes_params["text"] = request.form.get('text', aes_params.get("text"))
        app.config['LAST_PLAIN_TEXT_STR'] = aes_params["text"]
    else:
        if app.config['LAST_PLAIN_TEXT_STR']:
            aes_params["text"] = app.config['LAST_PLAIN_TEXT_STR']
            app.config['LAST_PLAIN_TEXT_STR'] = ''
    core_logger = _get_core_logger()
    return AsyncAudioStream(wav=WavAudioNFSK(**global_get_wav_fsk_params(request.args), logger=handler.logger), crypter=AESCrypterBase.from_config(aes_params), logger=handler.logger).start()


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
    core_logger = _get_core_logger()
    return AsyncAudioStream(wav=WavAudioNFSK(**global_get_wav_fsk_params(request.args), logger=core_logger), crypter=AESCrypterBase.from_config(global_get_aes_params(request.args)), logger=core_logger).wav_aes_nfsk_decrypt(request.data), 200

# -------------------- wav ---------------------------
# -------------------- tox ---------------------------


@app.route('/tox/send_message', methods=['GET'])
@internal_server_error_throwable
@authentication_required
def tox_send_message_endpoint():
    handler = _get_core_handler()
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
    handler = _get_core_handler()
    if not handler.tox_instance or not handler.tox_instance.is_running:
        return "Tox client is not running", HTTPCodes.SERVICE_UNAVAILABLE.value
    try:
        count: int = int(request.args.get("count", handler.private_data.tox_config.instance_config.input_queue_max_size))
    except ValueError:
        return f"Count param is invalid: {request.args.get("count")}", HTTPCodes.NOT_ACCEPTABLE.value
    return Response([item.to_json() for item in handler.tox_instance.output_queue.get_batch(count)], mimetype='application/json')

# -------------------- tox ---------------------------
# -------------------- meshtastic --------------------


def get_instance_by_id(service: str):
    def factory(f: Callable) -> Callable:
        @wraps(f)
        def instance_valudator(*args, **kwargs):
            handler = _get_core_handler()
            if not handler:
                return "Instances structure is not initialized yet", HTTPCodes.SERVICE_UNAVAILABLE.value
            match service:
                case "meshtastic":
                    instances = handler.meshtastic_instances
                case "meshcore":
                    instances = handler.meshcore_instances
                case _:
                    return "Instances structure is not exists", HTTPCodes.SERVICE_UNAVAILABLE.value
            if len(instances) < 1:
                return "Instances structure is empty", HTTPCodes.NOT_FOUND.value
            if len(instances) == 1:
                instance = list(instances.values())[0]
                handler.logger.debug(f"Found only one node: {instance.name}")
            else:
                instance_id = f"{service}_{request.args.get('ID')}"
                instance = instances.get(instance_id)

            if not instance.is_running:
                return f"Instance with ID {instance.name} is not running", HTTPCodes.SERVICE_UNAVAILABLE.value
            return f(instance, *args, **kwargs)
        return instance_valudator
    return factory


@app.route('/meshtastic/get_nodes', methods=['GET'])
@authentication_required
@get_instance_by_id("meshtastic")
def meshtastic_get_nodes_endpoint(instance: MeshtasticWireHandleThread):
    if result := instance.get_all_known_nodes():
        response: str = instance.json_dumps_nodes(result)
        nodes_info: List[str] = response.split("},")
        slice_len: int = 5
        if len(nodes_info) > slice_len*2:
            nodes_info = nodes_info[:slice_len] + nodes_info[-slice_len:]
        _get_core_logger().dump(f"Nodes summary(first and last {slice_len}):\n {'},'.join(nodes_info)}")
        return Response(response, mimetype='application/json')
    else:
        return "Nodes not found", HTTPCodes.NOT_FOUND.value


@app.route('/meshtastic/send_message', methods=['GET'])
@authentication_required
@get_instance_by_id("meshtastic")
def meshtastic_send_message_endpoint(instance: MeshtasticWireHandleThread):
    MAX_TEXT_LENGTH: int = 160
    if instance:
        if not instance.is_running:
            return f"Node with ID {instance.name} is not running", HTTPCodes.SERVICE_UNAVAILABLE.value
        if text := request.args.get("text"):
            if len(text) > MAX_TEXT_LENGTH:
                return f"Text message too large: {len(text)} > {MAX_TEXT_LENGTH}!", HTTPCodes.CONTENT_TOO_LARGE.value
            try:
                instance._send_message(text, int(request.args.get("ch", 0)), int(request.args.get("to", -1)))
                return "", HTTPCodes.OK.value
            except ValueError:
                msg = f"Channel index: {request.args.get("ch")} and destination id: {request.args.get("to")} must be integers!"
            except Exception as e:
                msg = f"Exception while sending message: {e}"
            _get_core_logger().exception(msg)
            return msg, HTTPCodes.NOT_ACCEPTABLE.value
        else:
            return "Message text is not set", HTTPCodes.MISDIRECTED_REQUEST.value
    else:
        return "Node not found", HTTPCodes.NOT_FOUND.value


@app.route('/meshtastic/get_messages', methods=['GET'])
@internal_server_error_throwable
@authentication_required
@get_instance_by_id("meshtastic")
def meshtastic_get_messages_endpoint(instance: MeshtasticWireHandleThread):
    if instance:
        if not instance.is_running:
            return f"Node with ID {instance.name} is not running", HTTPCodes.SERVICE_UNAVAILABLE.value
        try:
            count: int = int(request.args.get("count", 250))
        except ValueError:
            return f"Count param is invalid: {request.args.get("count")}", HTTPCodes.NOT_ACCEPTABLE.value
        return Response(json.dumps([item.to_json(_get_core_logger()) for item in instance._output_queue.get_batch(count)], default=mesh_json_serial, ensure_ascii=False, indent=4),
                        mimetype='application/json')
    else:
        return f"Node with ID {request.args.get("ID")} not found", HTTPCodes.NOT_FOUND.value

# -------------------- meshtastic --------------------

# -------------------- MAIN --------- -----------


def main() -> None:
    __default_key: str = "898946929E5274DDE600CD7788B6C557377716197A59A6C5D9063A22C9E40741" # TODO: Remove
    # -- Parse args
    parser = argparse.ArgumentParser(description="ws-http-endpoint")
    parser.add_argument('-k', '--key', type=str, default=__default_key, help='Key for decrypting private data (AES-256 CBC)')
    parser.add_argument('-p', '--port', type=int, default=60600, help='port(default=%(default)s)')
    parser.add_argument("-d", "--debug", default=True, help="enable debug mode(default=%(default)s)")
    args = parser.parse_args()

    _init_global_cache_at_boot(args.key)
    app.run(host='0.0.0.0', port=args.port, debug=True, use_reloader=True)


if __name__ == '__main__':
        main()
