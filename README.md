# ws-http-endpoint
Custom `Flask` `HTTP` endpoint for default WS with external IP.

❌ DO NOT USING THIS PROJECT IN PRODUCTION ❌
## Basic usage
### Startup
```
python3 -m ws_endpoint.py [-h] [-p PORT] [-d DEBUG]

ws-http-endpoint

options:
  -h, --help                show this help message and exit
  -k KEY, --key             key for decrypting private data (AES-256 CBC). Recommended for production use only!
  -p PORT, --port PORT      port(default=60600)
  -d DEBUG, --debug DEBUG   enable debug mode(default=True)
```

### Getting runtime status & all services information with endpoints + parameters description and presets (json)
```
curl -X GET http://{IP}:{PORT}/
```

## Endpoints
### wav
___
A  service for generating, transmitting, and decrypting `WAV` streams encoded with binary data (pre-encrypted using `AES-256` in `GCM`/`CBC` modes) using static or dynamic `N-FSK` modulation.\
Supports arbitrary frequency, number of channels, and data formats for representing sampling widths (from `uint8` to `uint64` or `float64`).\
Allows to create infinite audio streams based on random data, even with non-standard parameters (ex: `int64` per sample, more than different `64` channels or `MHz`+ sample rate value).

### tox
___
**WIP**

### mesh
___
A service for remotely managing nodes in mesh networks, such as `meshtastic` or `meshcore`.

Basic commands:
- Get a list of known nodes
- Send a message
- Receive incoming messages
- Get metrics for the node in use.

### SMMSGateway
___
**WIP**

## TODO, Features, Bugs, Changelog, etc
___
### WIP
- Dynamic FSK & Smooth generation(decryption already supported).
### Features
- _Different_ data for _different_ channels.
- Detecting symbols by _intervals_, but not by single values while decryption.
- ~~`/wav/text/aes256_N-FSK/decrypter`.~~
- ~~Smoothing symbols values.~~
- ~~Dynamic smoothing symbols values.~~
- _Negative_ smoothing symbols values.
- Dynamic negative smoothing symbols values.
- ~~Add dynamic FSK and dynamic smoothing to crypter form.~~
- ~~Decryptor file size limit.~~

### Bugs
- Incorrect max value(+1) with 64 bit types in `_create_value_symbols`.
- Browser requests twice same stream `request.range` 
- `crypter` `POST` bug.
