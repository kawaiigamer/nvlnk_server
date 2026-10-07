# ws endpoint
Custom `HTTP` endpoint written on `Flask` for default **WS** with external IP.

❌ DO NOT YET USE THIS PROJECT IN PRODUCTION ❌

# Basic usage
## Startup
```
$ python3 -m ws_endpoint.py [-h] [-k KEY] [-p PORT] [-d DEBUG]

ws-http-endpoint

options:
  -h, --help                show this help message and exit
  -k KEY, --key             key for decrypting private data (AES-256 CBC). Recommended for production use only!
  -p PORT, --port PORT      port(default=60600)
  -d DEBUG, --debug DEBUG   enable debug mode(default=True)
```

## Getting runtime status & all services information with endpoints + parameters description and presets (json)
```
$ curl -X GET http://{IP}:{PORT}/
```

## If any endpoint needs authentication
```
$ curl -X GET http://{IP}:{PORT}/any/endpoint?param1=foo&param2=bar --cookie "access_key=7E74516EFA4FD55DE3E7CD017DF7D364D2DF7B94122740476DFBFB5F10523D6F"
```

## Count all code lines(all empty or tabs or spaces only strings will be ignored)
```
$ git ls-files  | grep "\.py$" | xargs awk 'NF' | wc -l
```

# Endpoints
- ##### ✅ - Final release, 🆗 - Awaiting final tests, 🈸 - WIP,  🈵 - Development in planning, ⏸️ - Paused,
- ##### 🈲 - Needs rework, 🆘 - Bug,  ❌ - Canceled,
- ##### 🆙 - Last updated, 🆕  - New.

## 🈸 wav
___
A  service for generating, transmitting, and decrypting `WAV` streams encoded with binary data (pre-encrypted using `AES-256` in `GCM`/`CBC` modes) using static or dynamic `N-FSK` modulation.\
Supports arbitrary frequency, number of channels, and data formats for representing sampling widths (from `uint8` to `uint64` or `float64`).\
Allows to create infinite audio streams based on random data, even with non-standard parameters (ex: `int64` per sample, more than different `64` channels or `MHz`+ sample rate value).

## 🈸 Mesh Networks
___
A service for remotely managing nodes in mesh networks, such as `meshtastic` or `meshcore`.

### 🆗 tox
Basic commands:
- 🆗 Load saved profile from file.
- 🆗 Create new profile file using any private key.
- 🆗 Save profile to file.
- 🆗 Accept invite.
- 🆗 Send a message.
- 🆗 Receive incoming messages.
- 🆗 DB for nodes.

### 🆗 Meshtastic
Basic commands:
- 🆗 Get a list of known nodes.
- 🆗 Send a message.
- 🆗 Receive incoming messages.
- 🆗 Save metrics for the node in use.

### 🈵 Meshcore
- 🈵 **WIP**

## 🈵 SMMSGateway
___
- 🈵 **WIP**

## TODO, WIP, Features, Bugs, Changelog, etc
___
### WIP
- 🈵 Dynamic FSK & Smooth generation(decryption already supported).

- 🆕 ! Use _--key_ arg for work with server private config & fix `global_get_private_data`.

- 🆕 Rework `StreamsStorage`.
- 🆕 Sending commands to threads.
- 🆕 Rework audio streaming service.

### Features
- ✅ ~~Adding central logging system.~~
- ✅ ~~Working with _different_ mesh nodes.~~
- ✅ ~~`/wav/text/aes256_N-FSK/decrypter`.~~
- ✅ ~~Smoothing symbols values.~~
- ✅ ~~Dynamic smoothing symbols values.~~
- ✅ ~~Add dynamic FSK and dynamic smoothing to crypter form.~~
- ✅ ~~Decryptor file size limit.~~
- ✅ ~~Add float as symbols.~~
- ✅ ~~Create core module that handle for threads.~~
- ✅ ~~Create endpoints for _tox_ and _meshtastic_.~~
- ✅ ~~Split `MeshtasticKnownNode` per static and dynamic parts.~~
- ✅ ~~Refactor folders with _src_.~~
- ✅ ~~Сorrect `cryptography` module.~~
- ✅ ~~Write unittests for `cryptography` module.~~
- ✅ ~~Create one global chash for all handlers of all instances.~~
- 🆙 _Different_ data for _different_ audio channels.
- 🆙 Detecting symbols by _intervals_, but not by single values while decryption.
- 🆙 _Negative_ smoothing symbols values.
- 🆙 Dynamic negative smoothing symbols values.

### Bugs
- ✅ ~~Incorrect max value(+1) with 64 bit types in `_create_value_symbols`.~~
- 🆘 Browser requests twice same stream `request.range` 
- 🆘 `crypter` `POST` bug.
- 🆘 If `create_fsk_frame` uses not `int16`, exception.