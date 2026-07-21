import argparse

from functools import wraps

from flask import Flask, request, Response
from werkzeug.exceptions import InternalServerError

from server_description import get_wav_params, get_aes_params, get_wav_fsk2_params, get_system_info
from server_audio import AsyncRandomAudioStream, WavAudio, AesGCM, WavAudioFSK2

app = Flask(__name__)


def internal_server_error_throwable(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as ve:
            raise InternalServerError(ve)
    return decorated_function


@app.route("/")
def main_page():
    return Response(get_system_info(), mimetype='application/json')


@app.route('/wav/random/stream')
@internal_server_error_throwable
def wav_random_stream():
    return AsyncRandomAudioStream(wav=WavAudio(**get_wav_params(request.args)), crypter=None).start()


@app.route('/wav/random/FSK2/stream')
@internal_server_error_throwable
def wav_random_fsk2_stream():
    return AsyncRandomAudioStream(wav=WavAudioFSK2(**get_wav_fsk2_params(request.args)), crypter=None).start()


@app.route('/wav/random/aes256/stream')
@internal_server_error_throwable
def wav_random_aes256_stream():
    return AsyncRandomAudioStream(wav=WavAudio(**get_wav_params(request.args)), crypter=AesGCM(**get_aes_params(request.args))).start()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="ws-http-endpoint")
    parser.add_argument('-p', '--port', type=int, default=60600, help='port(default=%(default)s)')
    parser.add_argument("-d", "--debug", default=True, help="enable debug mode(default=%(default)s)")
    args = parser.parse_args()
    app.run(host='0.0.0.0', port=args.port, debug=args.debug)
