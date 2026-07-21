# ws-http-endpoint

Http endpoint for default WS.

## Usage
```
python3 -m ws_endpoint.py [-h] [-p PORT] [-d DEBUG]

ws-http-endpoint

options:
  -h, --help                show this help message and exit
  -p PORT, --port PORT      port(default=60600)
  -d DEBUG, --debug DEBUG   enable debug mode(default=True)
```
## Get runtime status & services endpoints information

```
curl -X GET http://{IP}:{PORT}/
```

