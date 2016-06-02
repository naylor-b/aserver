from __future__ import print_function

import re
import socket
import sys
import logging


class Stream(object):
    """
    Stream abstraction on top of socket, supporting AnalysisServer protocol.
    Inspired by telnetlib, but drops 'cooking' of data.

    sock: socket
        Socket to wrap.

    dbg_send: bool
        If True then sent message data is shown on stdout.

    dbg_recv: bool
        If True then received message data is shown on stdout.
    """

    def __init__(self, sock, dbg_send=False, dbg_recv=False):
        if dbg_send or dbg_recv:  # pragma no cover
            logging.debug('Stream', sock.getsockname(), sock.getpeername())
        self._sock = sock
        self._peer = '%s:%s' % sock.getpeername()[:2]
        self._recv_buffer = ''
        self._raw = False
        self._dbg_send = dbg_send
        self._dbg_recv = dbg_recv

        # _expect() patterns
        self._request_id = map(re.compile, ['^setID [0-9]*\n'])
        self._request_len = map(re.compile, ['^bg\n', '^cmdLen=[0-9]*\n'])
        self._reply_id = map(re.compile, ['^[0-9]*\r\n'])
        self._reply_len = map(re.compile, ['^[0-9]*\r\n'])
        self._formats = map(re.compile, ['^format: string\r\n',
                                         '^format: error\r\n',
                                         '^format: PHXIcon\r\n'])
        self._cooked_request = map(re.compile, ['^.*\n'])
        self._cooked_reply = map(re.compile, ['\r\n>$', '^>$'])

    def _get_raw(self):
        """ Return True if in 'raw' mode. """
        return self._raw

    def _set_raw(self, value):
        """ Set 'raw' mode. """
        if not self._raw and value:
            self._raw = True
        else:
            raise ValueError("Can only transition from 'cooked' to 'raw'")

    raw = property(_get_raw, _set_raw, doc="True if in 'raw' mode")

    def send_request(self, request, request_id=None, background=False):
        """
        Send `request` to server.
        If in 'raw' mode use `request_id` and `background`.

        request: string
            Message to send.

        request_id: string
            Request identifier, used in 'raw' mode.

        background: bool
            'Raw' mode background processing flag.
        """
        if self._raw:
            if self._dbg_send:  # pragma no cover
                zero = request.find('\x00')
                if zero >= 0:
                    logging.debug('\nREQUEST to %s: id=%d, bg=%s, req=%r <+binary...>'
                          % (self._peer, request_id, background, request[:zero]))
                else:
                    logging.debug('\nREQUEST to %s: id=%d, bg=%s, request=%r'
                          % (self._peer, request_id, background, request))
            req = ['setID %s\n' % request_id]
            if background:
                req.append('bg\n')
            length = len(request)
            req.append('cmdLen=%d\n' % length)
            if length <= 32:  # The value 32 is not critical here.
                req.append(request)
                self._send(''.join(req))
            else:
                self._send(''.join(req))
                self._send(request)
        else:
            if self._dbg_send:  # pragma no cover
                logging.debug('\nREQUEST to %s: request=%r' % (self._peer, request))
            self._send('%s\r\n' % request)

    def recv_request(self):
        """ Receive request from client. """
        if self._dbg_recv:  # pragma no cover
            logging.debug('\nREQUEST from %s:' % self._peer)
        if self._raw:
            info = self._expect(self._request_id)
            args = info[2].split()
            request_id = int(args[1])
            if self._dbg_recv:  # pragma no cover
                logging.debug('    request_id', request_id)

            info = self._expect(self._request_len)
            if info[2].strip() == 'bg':
                background = True
                if self._dbg_recv:  # pragma no cover
                    logging.debug('    background')
                info = self._expect(self._request_len)
            else:
                background = False
            args = info[2].split('=')
            length = int(args[1])
            if self._dbg_recv:  # pragma no cover
                logging.debug('    length', length)

            request = self._recv(length)
            if self._dbg_recv:  # pragma no cover
                zero = request.find('\x00')
                if zero >= 0:
                    logging.debug('    req %r <+binary...>' % request[:zero])
                else:
                    logging.debug('    request %r' % request)
            return (request, request_id, background)
        else:
            info = self._expect(self._cooked_request)
            request = info[2].strip()
            if self._dbg_recv:  # pragma no cover
                logging.debug('    request %r' % request)
            return request

    def send_reply(self, reply, reply_id=None, format='string'):
        """
        Send `reply` to client.
        If in 'raw' mode use `reply_id` and `format`.

        reply: string
            Message to be sent.

        reply_id: string
            Reply identifier, used in 'raw' mode.

        format: string
            Reply message format: 'string', 'error', or 'PHXIcon'.
        """
        if self._raw:
            if self._dbg_send:  # pragma no cover
                zero = reply.find('\x00')
                if zero >= 0:
                    logging.debug('\nREPLY to %s: id=%d, format=%s, reply=%r <+binary...>'
                          % (self._peer, reply_id, format, reply[:zero]))
                else:
                    logging.debug('\nREPLY to %s: id=%d, format=%s, reply=%r'
                          % (self._peer, reply_id, format, reply))
            length = len(reply)
            msg = '%d\r\nformat: %s\r\n%d\r\n' % (reply_id, format, length)
            if length <= 32:  # The value 32 is not critical here.
                msg += reply
                self._send(msg)
            else:
                self._send(msg)
                self._send(reply)
        else:
            if self._dbg_send:  # pragma no cover
                logging.debug('\nREPLY to %s: reply=%r' % (self._peer, reply))
            if reply:
                reply = reply.replace('\n', '\r\n')
                if reply.endswith('\n>'):
                    self._send(reply)
                else:
                    self._send('%s\r\n>' % reply)
            else:
                self._send('>')

    def recv_reply(self):
        """ Receive reply from server. """
        if self._dbg_recv:  # pragma no cover
            logging.debug('\nREPLY from %s:' % self._peer)
        if self._raw:
            info = self._expect(self._reply_id)
            reply_id = int(info[2])
            if self._dbg_recv:  # pragma no cover
                logging.debug('    reply_id', reply_id)

            info = self._expect(self._formats)
            args = info[2].split()
            format = args[1].strip()
            if self._dbg_recv:  # pragma no cover
                logging.debug('    format %r' % format)

            info = self._expect(self._reply_len)
            length = int(info[2])
            if self._dbg_recv:  # pragma no cover
                logging.debug('    length', length)

            reply = self._recv(length)
            if self._dbg_recv:  # pragma no cover
                zero = reply.find('\x00')
                if zero >= 0:
                    logging.debug('    reply %r <+binary...>' % reply[:zero])
                else:
                    logging.debug('    reply %r' % reply)
            return (reply, reply_id, format)
        else:
            info = self._expect(self._cooked_reply)
            reply = info[2]
            reply = reply.replace('\r\n', '\n')
            if self._dbg_recv:  # pragma no cover
                logging.debug('    reply %r' % reply)
            return reply

    def _send(self, data):
        """
        Send `data`.

        data: string
            Data to send.
        """
        length = len(data)
        start = 0
        chunk = 1 << 17  # 128KB, chunking allows for send/recv overlap.
        while start < length:
            end = start + chunk
            self._sock.sendall(data[start:end])
            start = end

    def _expect(self, patterns):
        """
        Wait for one or more patterns to match.
        Return (index, match_obj, data).

        patterns: list[regex]
            List of regex patterns
        """
        while True:
            for i, pattern in enumerate(patterns):
                match_obj = pattern.search(self._recv_buffer)
                if match_obj is not None:
                    end = match_obj.end()
                    data = self._recv_buffer[:end]
                    self._recv_buffer = self._recv_buffer[end:]
                    return (i, match_obj, data)
            self._receive()

    def _recv(self, length):
        """
        Return next `length` bytes.

        length: int
            Number of bytes to be received.
        """
        while len(self._recv_buffer) < length:
            self._receive()
        data = self._recv_buffer[:length]
        self._recv_buffer = self._recv_buffer[length:]
        return data

    def _receive(self):
        """ Receive more data. """
        try:
            data = self._sock.recv(4096)
        except socket.error as exc:  # pragma no cover
            if sys.platform == 'win32':
                if exc.errno == 10053 or exc.errno == 10054:
                    raise EOFError('Connection to %s closed' % self._peer)
            elif 'Connection reset by peer' in str(exc):
                raise EOFError('Connection to %s closed' % self._peer)
            raise
        if data:
            self._recv_buffer += data
        else:
            raise EOFError('Connection to %s closed' % self._peer)
