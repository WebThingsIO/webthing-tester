#!/usr/bin/env python3

import argparse
import json
import re
import socket
import time
import tornado.httpclient
import tornado.websocket
import websocket


_TIME_REGEX = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$'
_PROTO = None
_BASE_URL = None
_PATH_PREFIX = None
_AUTHORIZATION_HEADER = None
_DEBUG = False


def get_ip():
    """
    Get the default local IP address.

    From: https://stackoverflow.com/a/28950776
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except (socket.error, IndexError):
        ip = '127.0.0.1'
    finally:
        s.close()

    return ip


def http_request(method, path, data=None):
    """
    Send an HTTP request to the server.

    method -- request method, i.e. 'GET'
    path -- request path
    data -- optional data to include
    """
    url = _PROTO + '://' + _BASE_URL + _PATH_PREFIX + path
    url = url.rstrip('/')

    client = tornado.httpclient.HTTPClient()

    fake_host = 'localhost'
    if ':' in _BASE_URL:
        fake_host += ':' + _BASE_URL.split(':')[1]

    headers = {
        'Host': fake_host,
        'Accept': 'application/json',
    }

    if _DEBUG:
        if data is None:
            print('Request:  {} {}'.format(method, url))
        else:
            print('Request:  {} {}\n          '.format(method, url, data))

    if _AUTHORIZATION_HEADER is not None:
        headers['Authorization'] = _AUTHORIZATION_HEADER

    if data is None:
        request = tornado.httpclient.HTTPRequest(
            url,
            method=method,
            headers=headers,
        )
    else:
        headers['Content-Type'] = 'application/json'
        request = tornado.httpclient.HTTPRequest(
            url,
            method=method,
            headers=headers,
            body=json.dumps(data),
        )

    response = client.fetch(request, raise_error=False)

    if response.body:
        if _DEBUG:
            print('Response: {} {}\n'
                  .format(response.code, response.body.decode()))

        return response.code, json.loads(response.body.decode())
    else:
        if _DEBUG:
            print('Response: {}\n'.format(response.code))

        return response.code, None


def lists_equal(a, b):
    if len(a) != len(b):
        return False

    intersection = set(a) & set(b)
    return len(intersection) == len(a)


def run_client():
    """Test the web thing server."""
    # Test thing description
    code, body = http_request('GET', '/')
    assert code == 200
    assert body['name'] == 'My Lamp'
    assert body['@context'] == 'https://iot.mozilla.org/schemas'
    assert lists_equal(body['@type'], ['OnOffSwitch', 'Light'])
    assert body['description'] == 'A web connected lamp'
    assert body['properties']['on']['@type'] == 'OnOffProperty'
    assert body['properties']['on']['label'] == 'On/Off'
    assert body['properties']['on']['type'] == 'boolean'
    assert body['properties']['on']['description'] == 'Whether the lamp is turned on'
    assert body['properties']['on']['href'] == _PATH_PREFIX + '/properties/on'
    assert body['properties']['brightness']['@type'] == 'BrightnessProperty'
    assert body['properties']['brightness']['label'] == 'Brightness'
    assert body['properties']['brightness']['type'] == 'number'
    assert body['properties']['brightness']['description'] == 'The level of light from 0-100'
    assert body['properties']['brightness']['minimum'] == 0
    assert body['properties']['brightness']['maximum'] == 100
    assert body['properties']['brightness']['unit'] == 'percent'
    assert body['properties']['brightness']['href'] == _PATH_PREFIX + '/properties/brightness'
    assert body['actions']['fade']['label'] == 'Fade'
    assert body['actions']['fade']['description'] == 'Fade the lamp to a given level'
    assert body['actions']['fade']['input']['type'] == 'object'
    assert body['actions']['fade']['input']['properties']['brightness']['type'] == 'number'
    assert body['actions']['fade']['input']['properties']['brightness']['minimum'] == 0
    assert body['actions']['fade']['input']['properties']['brightness']['maximum'] == 100
    assert body['actions']['fade']['input']['properties']['brightness']['unit'] == 'percent'
    assert body['actions']['fade']['input']['properties']['duration']['type'] == 'number'
    assert body['actions']['fade']['input']['properties']['duration']['minimum'] == 1
    assert body['actions']['fade']['input']['properties']['duration']['unit'] == 'milliseconds'
    assert body['actions']['fade']['href'] == _PATH_PREFIX + '/actions/fade'
    assert body['events']['overheated']['type'] == 'number'
    assert body['events']['overheated']['unit'] == 'celsius'
    assert body['events']['overheated']['description'] == 'The lamp has exceeded its safe operating temperature'
    assert body['events']['overheated']['href'] == _PATH_PREFIX + '/events/overheated'
    assert len(body['links']) >= 4
    assert body['links'][0]['rel'] == 'properties'
    assert body['links'][0]['href'] == _PATH_PREFIX + '/properties'
    assert body['links'][1]['rel'] == 'actions'
    assert body['links'][1]['href'] == _PATH_PREFIX + '/actions'
    assert body['links'][2]['rel'] == 'events'
    assert body['links'][2]['href'] == _PATH_PREFIX + '/events'
    assert body['links'][3]['rel'] == 'alternate'

    ws_href = None
    for link in body['links'][3:]:
        if 'mediaType' in link:
            assert link['mediaType'] == 'text/html'
            assert link['href'] == _PATH_PREFIX
        else:
            proto = 'wss' if _PROTO == 'https' else 'ws'
            assert re.match(
                proto + r'://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}' + _PATH_PREFIX,
                link['href'])
            ws_href = link['href']

    # Test properties
    code, body = http_request('GET', '/properties/brightness')
    assert code == 200
    assert body['brightness'] == 50

    code, body = http_request('PUT', '/properties/brightness', {'brightness': 25})
    assert code == 200
    assert body['brightness'] == 25

    code, body = http_request('GET', '/properties/brightness')
    assert code == 200
    assert body['brightness'] == 25

    # Test events
    code, body = http_request('GET', '/events')
    assert code == 200
    assert len(body) == 0

    # Test actions
    code, body = http_request('GET', '/actions')
    assert code == 200
    assert len(body) == 0

    code, body = http_request(
        'POST',
        '/actions',
        {
            'fade': {
                'input': {
                    'brightness': 50,
                    'duration': 2000,
                },
            },
        })
    assert code == 201
    assert body['fade']['input']['brightness'] == 50
    assert body['fade']['input']['duration'] == 2000
    assert body['fade']['href'].startswith(_PATH_PREFIX + '/actions/fade/')
    assert body['fade']['status'] == 'created'
    action_id = body['fade']['href'].split('/')[-1]

    # Wait for the action to complete
    time.sleep(2.5)

    code, body = http_request('GET', '/actions')
    assert code == 200
    assert len(body) == 1
    assert len(body[0].keys()) == 1
    assert body[0]['fade']['input']['brightness'] == 50
    assert body[0]['fade']['input']['duration'] == 2000
    assert body[0]['fade']['href'] == _PATH_PREFIX + '/actions/fade/' + action_id
    assert re.match(_TIME_REGEX, body[0]['fade']['timeRequested']) is not None
    assert re.match(_TIME_REGEX, body[0]['fade']['timeCompleted']) is not None
    assert body[0]['fade']['status'] == 'completed'

    code, body = http_request('DELETE', '/actions/fade/' + action_id)
    assert code == 204
    assert body is None

    # The action above generates an event, so check it.
    code, body = http_request('GET', '/events')
    assert code == 200
    assert len(body) == 1
    assert len(body[0].keys()) == 1
    assert body[0]['overheated']['data'] == 102
    assert re.match(_TIME_REGEX, body[0]['overheated']['timestamp']) is not None

    # Set up a websocket
    ws = websocket.WebSocket()
    if _AUTHORIZATION_HEADER is not None:
        ws_href += '?jwt=' + _AUTHORIZATION_HEADER.split(' ')[1]

    ws.connect(ws_href)

    # Test setting property through websocket
    ws.send(json.dumps({
        'messageType': 'setProperty',
        'data': {
            'brightness': 10,
        }
    }))
    message = json.loads(ws.recv())
    assert message['messageType'] == 'propertyStatus'
    assert message['data']['brightness'] == 10

    code, body = http_request('GET', '/properties/brightness')
    assert code == 200
    assert body['brightness'] == 10

    # Test requesting action through websocket
    ws.send(json.dumps({
        'messageType': 'requestAction',
        'data': {
            'fade': {
                'input': {
                    'brightness': 90,
                    'duration': 1000,
                },
            },
        }
    }))

    # Handle any extra propertyStatus message first
    while True:
        message = json.loads(ws.recv())
        if message['messageType'] == 'propertyStatus':
            continue

        break

    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['brightness'] == 90
    assert message['data']['fade']['input']['duration'] == 1000
    assert message['data']['fade']['href'].startswith(_PATH_PREFIX + '/actions/fade/')
    assert message['data']['fade']['status'] == 'created'
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['brightness'] == 90
    assert message['data']['fade']['input']['duration'] == 1000
    assert message['data']['fade']['href'].startswith(_PATH_PREFIX + '/actions/fade/')
    assert message['data']['fade']['status'] == 'pending'

    # These may come out of order
    action_id = None
    received = [False, False]
    for _ in range(0, 2):
        message = json.loads(ws.recv())

        if message['messageType'] == 'propertyStatus':
            assert message['data']['brightness'] == 90
            received[0] = True
        elif message['messageType'] == 'actionStatus':
            assert message['data']['fade']['input']['brightness'] == 90
            assert message['data']['fade']['input']['duration'] == 1000
            assert message['data']['fade']['href'].startswith(_PATH_PREFIX + '/actions/fade/')
            assert message['data']['fade']['status'] == 'completed'
            action_id = message['data']['fade']['href'].split('/')[-1]
            received[1] = True
        else:
            raise ValueError('Wrong message: {}'.format(message['messageType']))

    for r in received:
        assert r

    code, body = http_request('GET', '/actions')
    assert code == 200
    assert len(body) == 1
    assert len(body[0].keys()) == 1
    assert body[0]['fade']['input']['brightness'] == 90
    assert body[0]['fade']['input']['duration'] == 1000
    assert body[0]['fade']['href'] == _PATH_PREFIX + '/actions/fade/' + action_id
    assert re.match(_TIME_REGEX, body[0]['fade']['timeRequested']) is not None
    assert re.match(_TIME_REGEX, body[0]['fade']['timeCompleted']) is not None
    assert body[0]['fade']['status'] == 'completed'

    code, body = http_request('GET', '/actions/fade/' + action_id)
    assert code == 200
    assert len(body.keys()) == 1
    assert body['fade']['href'] == _PATH_PREFIX + '/actions/fade/' + action_id
    assert re.match(_TIME_REGEX, body['fade']['timeRequested']) is not None
    assert re.match(_TIME_REGEX, body['fade']['timeCompleted']) is not None
    assert body['fade']['status'] == 'completed'

    code, body = http_request('GET', '/events')
    assert code == 200
    assert len(body) == 2
    assert len(body[1].keys()) == 1
    assert body[1]['overheated']['data'] == 102
    assert re.match(_TIME_REGEX, body[1]['overheated']['timestamp']) is not None

    # Test event subscription through websocket
    ws.send(json.dumps({
        'messageType': 'addEventSubscription',
        'data': {
            'overheated': {},
        }
    }))
    ws.send(json.dumps({
        'messageType': 'requestAction',
        'data': {
            'fade': {
                'input': {
                    'brightness': 100,
                    'duration': 500,
                },
            },
        }
    }))
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['brightness'] == 100
    assert message['data']['fade']['input']['duration'] == 500
    assert message['data']['fade']['href'].startswith(_PATH_PREFIX + '/actions/fade/')
    assert message['data']['fade']['status'] == 'created'
    assert re.match(_TIME_REGEX, message['data']['fade']['timeRequested']) is not None
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['brightness'] == 100
    assert message['data']['fade']['input']['duration'] == 500
    assert message['data']['fade']['href'].startswith(_PATH_PREFIX + '/actions/fade/')
    assert message['data']['fade']['status'] == 'pending'
    assert re.match(_TIME_REGEX, message['data']['fade']['timeRequested']) is not None

    # These may come out of order
    received = [False, False, False]
    for _ in range(0, 3):
        message = json.loads(ws.recv())

        if message['messageType'] == 'propertyStatus':
            assert message['data']['brightness'] == 100
            received[0] = True
        elif message['messageType'] == 'event':
            assert message['data']['overheated']['data'] == 102
            assert re.match(_TIME_REGEX, message['data']['overheated']['timestamp']) is not None
            received[1] = True
        elif message['messageType'] == 'actionStatus':
            assert message['data']['fade']['input']['brightness'] == 100
            assert message['data']['fade']['input']['duration'] == 500
            assert message['data']['fade']['href'].startswith(_PATH_PREFIX + '/actions/fade/')
            assert message['data']['fade']['status'] == 'completed'
            assert re.match(_TIME_REGEX, message['data']['fade']['timeRequested']) is not None
            assert re.match(_TIME_REGEX, message['data']['fade']['timeCompleted']) is not None
            received[2] = True

    for r in received:
        assert r

    ws.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Web Thing test client.')
    parser.add_argument('--protocol',
                        help='protocol, either http or https',
                        choices=['http', 'https'],
                        default='http')
    parser.add_argument('--host',
                        help='server hostname or IP address',
                        default=get_ip())
    parser.add_argument('--port',
                        help='server port',
                        type=int,
                        default=8888)
    parser.add_argument('--path-prefix',
                        help='path prefix to get to thing description',
                        default='')
    parser.add_argument('--auth-header',
                        help='authorization header, i.e. "Bearer ..."')
    parser.add_argument('--debug',
                        help='log all requests',
                        action='store_true')
    args = parser.parse_args()

    if (args.protocol == 'http' and args.port == 80) or \
            (args.protocol == 'https' and args.port == 443):
        _BASE_URL = args.host
    else:
        _BASE_URL = '{}:{}'.format(args.host, args.port)

    if args.debug:
        _DEBUG = True

    _PROTO = args.protocol
    _PATH_PREFIX = args.path_prefix
    _AUTHORIATION_HEADER = args.auth_header

    exit(run_client())
