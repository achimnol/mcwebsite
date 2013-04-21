#! /usr/bin/env python
# -*- coding: utf8 -*-

from __future__ import print_function, with_statement
import sys, os, errno
import glob
from collections import namedtuple
import socket, struct
import mimetypes
from flask import Flask, request, abort, render_template

MC_PATH = '/home/daybreaker/minecraft'
base_path = os.path.abspath(os.path.dirname(__file__))
MCStatus = namedtuple('MCStatus', [
    'host', 'port', 'motd', 'gametype', 'version', 'plugins', 'num_players', 'max_players'
])

app = Flask(__name__)
application = app

def read_properties(filename):
    props = {}
    with open(filename, 'r') as f:
        for line in f:
            if not line or line.startswith('#'): continue
            parts = line.split('=')
            props[parts[0].strip()] = parts[1].strip()
    return props

def read_sock_safe(sock, size):
    while True:
        try:
            data, _addr = sock.recvfrom(size)
        except socket.error as e:
            if e.errno != errno.EINTR:
                raise
        else:
            return data

def query_status(addr):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    myid_token = 0x01020304

    # Do handshake.
    sock.sendto(struct.pack('>BBBi', 0xfe, 0xfd, 0x09, myid_token), addr)
    response = read_sock_safe(sock, 64)
    ssize = struct.calcsize('>Bi')
    reply = struct.unpack('>Bi', response[:ssize])
    assert 0x09 == reply[0]
    assert myid_token == reply[1]
    challenge_token = int(response[ssize:].strip('\0'))

    # Get status information.
    sock.sendto(struct.pack('>BBBiii', 0xfe, 0xfd, 0x00, myid_token, challenge_token, myid_token), addr)
    response = read_sock_safe(sock, 4096)

    def fetch_byte(buf):
        return buf[0], buf[1:]

    def fetch_str(buf):
        for i, c in enumerate(buf):
            if c == '\x00':
                break
        else:
            return '', buf
        return buf[:i].decode('utf8'), buf[i+1:] # skip null byte

    def fetch_int32(buf):
        ret = struct.unpack('>i', buf[:4])
        return ret[0], buf[4:]

    def fetch_short(buf):
        ret = struct.unpack('<h', buf[:2])
        return ret[0], buf[2:]

    msgtype, response = fetch_byte(response)
    assert msgtype == '\x00'
    replied_myid_token, response = fetch_int32(response)
    assert myid_token == replied_myid_token
    while True:
        field_name, response = fetch_str(response)
        if field_name == 'splitnum':
            _, response = fetch_short(response)
        elif field_name == 'hostname':
            motd, response = fetch_str(response)
        elif field_name == 'gametype':
            gametype, response = fetch_str(response)
        elif field_name == 'game_id':
            game_id, response = fetch_str(response)
            assert game_id == 'MINECRAFT'
        elif field_name == 'version':
            version, response = fetch_str(response)
        elif field_name == 'plugins':
            plugins, response = fetch_str(response)
        elif field_name == 'map':
            map_name, response = fetch_str(response)
        elif field_name == 'numplayers':
            num_players, response = fetch_str(response)
            num_players = int(num_players)
        elif field_name == 'maxplayers':
            max_players, response = fetch_str(response)
            max_players = int(max_players)
        elif field_name == 'hostip':
            hostname, response = fetch_str(response)
        elif field_name == 'hostport':
            host_port, response = fetch_str(response)
        else:
            break
    return MCStatus(hostname, host_port, motd, gametype, version, plugins, num_players, max_players)

def get_online():
    for name in os.listdir('/proc'):
        try:
            pid = int(name)
            cmdline = open('/proc/%d/cmdline' % pid, 'r').read()
            if 'minecraft_server.jar' in cmdline:
                return True
        except ValueError:
            continue
    return False

@app.route('/')
def status_page():
    status = {}
    status['online'] = get_online()
    conf = read_properties(os.path.join(MC_PATH, 'server.properties'))
    assert conf['enable-query'] == 'true'
    port = int(conf['server-port'] if 'query.port' not in conf else conf['query.port'])
    if status['online']:
        _status = query_status(('localhost', port))
        status['motd'] = _status.motd
        status['num_players'] = _status.num_players
        status['max_players'] = _status.max_players
        status['plugins'] = _status.plugins
        status['version'] = _status.version
    else:
        status['num_players'] = -1
        status['max_players'] = -1
        status['plugins'] = u'(서버가 꺼져있어 조회할 수 없음)'

    return render_template('status.html', status=status)

@app.route('/register', methods=['GET', 'POST'])
def register_page():
    if request.method == 'GET':

        msg = None
        return render_template('register.html', msg=msg)

    elif request.method == 'POST':

        new_name = str(request.form['mcid']).strip()
        if not new_name or '\n' in new_name or '\r' in new_name or '\0' in new_name:
            return abort(401)
        names = []
        whitelist_filename = os.path.join(base_path, 'white-list.txt')
        with open(whitelist_filename, 'r') as f:
            for line in f:
                if not line or line.startswith('#'): continue
                names.append(line.strip())
        if new_name in names:
            msg = u'이미 존재하는 ID입니다.'
        else:
            with open(whitelist_filename, 'a') as f:
                f.write('%s\n' % new_name)
            os.system("echo 'whitelist reload' > {0}".format(os.path.join(MC_PATH, 'stdin.fifo')))
            msg = u'등록되었습니다.'
        return render_template('register.html', msg=msg)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5019, debug=True)
