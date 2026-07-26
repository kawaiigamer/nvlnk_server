import argparse
import threading
import traceback
import uuid
from datetime import timedelta

from functools import wraps
from typing import Dict, Union

from flask import Flask, request, Response, render_template, session

from server_description import get_wav_params, get_aes_params, get_wav_fsk_params, get_system_info
from server_storage import StreamsStorage
from server_streaming import AsyncAudioStream, AsyncAudioStreamBase, WavAudio, WavAudioNFSK, AESCrypterBase

app = Flask(__name__)
app.permanent_session_lifetime = timedelta(seconds=10)
app.secret_key = uuid.uuid4().hex
streams_storage: StreamsStorage = StreamsStorage(clear_interval=timedelta(seconds=10), stream_lifetime=timedelta(seconds=10))


def internal_server_error_throwable(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as ve:
            tb = ve.__traceback__
            _, line_num, func_name, _ = traceback.extract_tb(tb)[-1]
            while tb.tb_next:
                tb = tb.tb_next
            if instance := tb.tb_frame.f_locals.get('self'):
                class_name = instance.__class__.__name__
            else:
                class_name = tb.tb_frame.f_locals.get('cls').__name__
            return {"error": f"Internal Server Error! [{class_name}::{line_num}:{func_name}] {str(ve)}"}, 500
    return decorated_function


def internal_stream_session_handler(f):
    @wraps(f)
    def decorated_stream_function(*args, **kwargs):
        print(f"request.range {request.range}, session.get('stream_uuid') = {session.get('stream_uuid')}", flush=True) #TODO: request.range bytes=3528044-, session.get('stream_uuid') = None
        if session_uuid := session.get('stream_uuid'):
            if storaged_stream := streams_storage.get_stream(session_uuid):
                new_stream: AsyncAudioStream = f(stream=storaged_stream, *args, **kwargs)
                print(f"Found in storage ={storaged_stream.stream_uuid}, new_stream {new_stream.stream_uuid}", flush=True)
            else:
                s = AsyncAudioStreamBase(uuid.uuid4().hex)
                new_stream: AsyncAudioStream = f(stream=s, *args, **kwargs)
                print(f"Found uuid in session but not stream in storage, StreamBase: {s.stream_uuid} new_stream {new_stream.stream_uuid}",flush=True)
        else:
            s = AsyncAudioStreamBase(uuid.uuid4().hex)
            new_stream: AsyncAudioStream = f(stream=s, *args, **kwargs)
            print(f"Not found uuid in session StreamBase: {s.stream_uuid}, new_stream {new_stream.stream_uuid}", flush=True)
        streams_storage.add_stream(new_stream.stream_uuid, new_stream)
        session['stream_uuid'] = new_stream.stream_uuid
        session.modified = True
        return new_stream.start()
    return decorated_stream_function


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route("/")
def main_page():
    return Response(get_system_info(), mimetype='application/json')


@app.route('/wav/random/stream')
@internal_server_error_throwable
@internal_stream_session_handler
def wav_random_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudio(**get_wav_params(request.args)))


@app.route('/wav/random/N-FSK/stream')
@internal_server_error_throwable
@internal_stream_session_handler
def wav_random_nfsk_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudioNFSK(**get_wav_fsk_params(request.args)))


@app.route('/wav/random/aes256/stream')
@internal_server_error_throwable
@internal_stream_session_handler
def wav_random_aes256_stream(stream: Union[AsyncAudioStream, AsyncAudioStreamBase]) -> AsyncAudioStream:
    if isinstance(stream, AsyncAudioStream):
        return stream
    return AsyncAudioStream.from_base(stream, wav=WavAudioNFSK(**get_wav_fsk_params(request.args), crypter=AESCrypterBase.from_config(get_aes_params(request.args))))





@app.route('/wav/random/aes256_N-FSK/stream')
@internal_server_error_throwable
def wav_random_aes256_nfsk_stream():
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args)), crypter=AESCrypterBase.from_config(get_aes_params(request.args))).start()




app.config['LAST_PLAIN_TEXT_STR'] = ''
@app.route('/wav/text/aes256_N-FSK/crypter', methods=['GET', 'POST'])
@internal_server_error_throwable
def wav_text_aes256_nfsk_crypter():
    aes_params = get_aes_params(request.args)
    if request.method == 'POST':
        aes_params["text"] = request.form.get('text', aes_params.get("text"))
        app.config['LAST_PLAIN_TEXT_STR'] = aes_params["text"]
    else:
        if app.config['LAST_PLAIN_TEXT_STR']:
            aes_params["text"] = app.config['LAST_PLAIN_TEXT_STR']
            app.config['LAST_PLAIN_TEXT_STR'] = ''
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args)), crypter=AESCrypterBase.from_config(aes_params)).start()


@app.route('/wav/text/aes256_N-FSK/crypter/form', methods=['GET'])
def wav_text_aes256_nfsk_crypter_form():
    return render_template('input_text.html')


@app.route('/wav/text/aes256_N-FSK/decrypter', methods=["GET", 'POST'])
@internal_server_error_throwable
def wav_text_aes256_nfsk_decrypter():
    if request.method == 'GET':
        return render_template('input_file.html')
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args)), crypter=AESCrypterBase.from_config(get_aes_params(request.args))).wav_aes_nfsk_decrypt(request.data), 200


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="ws-http-endpoint")
    parser.add_argument('-p', '--port', type=int, default=60600, help='port(default=%(default)s)')
    parser.add_argument("-d", "--debug", default=True, help="enable debug mode(default=%(default)s)")
    args = parser.parse_args()
    print(streams_storage.start())
    app.run(host='0.0.0.0', port=args.port, debug=args.debug, use_reloader=True)
