import argparse

from functools import wraps

from flask import Flask, request, Response, render_template
from werkzeug.exceptions import InternalServerError

from server_description import get_wav_params, get_aes_params, get_wav_fsk_params, get_system_info
from server_audio import AsyncAudioStream, WavAudio, WavAudioNFSK, AESBase

app = Flask(__name__)


def internal_server_error_throwable(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as ve:
            raise InternalServerError(ve)
    return decorated_function


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route("/")
def main_page():
    return Response(get_system_info(), mimetype='application/json')


@app.route('/wav/random/stream')
@internal_server_error_throwable
def wav_random_stream():
    return AsyncAudioStream(wav=WavAudio(**get_wav_params(request.args)), crypter=None, req_range=request.range).start()


@app.route('/wav/random/N-FSK/stream')
@internal_server_error_throwable
def wav_random_nfsk_stream():
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args)), crypter=None, req_range=request.range).start()


@app.route('/wav/random/aes256/stream')
@internal_server_error_throwable
def wav_random_aes256_stream():
    return AsyncAudioStream(wav=WavAudio(**get_wav_params(request.args)), crypter=AESBase.from_config(get_aes_params(request.args)), req_range=request.range).start()


@app.route('/wav/random/aes256_N-FSK/stream')
@internal_server_error_throwable
def wav_random_aes256_nfsk_stream():
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args)), crypter=AESBase.from_config(get_aes_params(request.args)), req_range=request.range).start()


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
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args)), crypter=AESBase.from_config(aes_params), req_range=request.range).start()


@app.route('/wav/text/aes256_N-FSK/crypter/form', methods=['GET'])
def wav_text_aes256_nfsk_crypter_form():
    return render_template('input_text.html')


@app.route('/wav/text/aes256_N-FSK/decrypter', methods=["GET", 'POST'])
@internal_server_error_throwable
def wav_text_aes256_nfsk_decrypter():
    if request.method == 'GET':
         return render_template('input_file.html')
    return AsyncAudioStream(wav=WavAudioNFSK(**get_wav_fsk_params(request.args)), crypter=AESBase.from_config(get_aes_params(request.args))).wav_aes_nfsk_decrypt(request.data), 200


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="ws-http-endpoint")
    parser.add_argument('-p', '--port', type=int, default=60600, help='port(default=%(default)s)')
    parser.add_argument("-d", "--debug", default=True, help="enable debug mode(default=%(default)s)")
    args = parser.parse_args()
    app.run(host='0.0.0.0', port=args.port, debug=args.debug, use_reloader=True)
