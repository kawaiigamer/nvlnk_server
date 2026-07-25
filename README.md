# ws-http-endpoint

Custom Http endpoint for default WS with external IP.

## Usage

```
python3 -m ws_endpoint.py [-h] [-p PORT] [-d DEBUG]

ws-http-endpoint

options:
  -h, --help                show this help message and exit
  -p PORT, --port PORT      port(default=60600)
  -d DEBUG, --debug DEBUG   enable debug mode(default=True)
```

## Getting runtime status & all services information with endpoints + parameters description and presets (json)

```
curl -X GET http://{IP}:{PORT}/
```
## TODO

### WIP
- Dynamic FSK & Smooth generation(decryption already supported).
### Features
- Different data for different channels.
- Detecting symbols by intervals, but not by single values while decryption.
- ~~`/wav/text/aes256_N-FSK/decrypter`.~~
- ~~Smoothing symbols values.~~
- ~~Dynamic smoothing symbols values.~~
- Negative smoothing symbols values.
- Dynamic negative smoothing symbols values.
- ~~Add dynamic FSK and dynamic smoothing to crypter form.~~
### Bugs
- Incorrect max value(+1) with 64 bit types in `_create_value_symbols`.
- Browser requests twice same stream `request.range` 
- `crypter` `POST` bug.
