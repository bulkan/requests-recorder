#!/usr/bin/env python

#############################################################################
# 
# Zope Public License (ZPL) Version 2.0
# -----------------------------------------------
# 
# This software is Copyright (c) Zope Corporation (tm) and
# Contributors. All rights reserved.
# 
# This license has been certified as open source. It has also
# been designated as GPL compatible by the Free Software
# Foundation (FSF).
# 
# Redistribution and use in source and binary forms, with or
# without modification, are permitted provided that the
# following conditions are met:
# 
# 1. Redistributions in source code must retain the above
#    copyright notice, this list of conditions, and the following
#    disclaimer.
# 
# 2. Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions, and the following
#    disclaimer in the documentation and/or other materials
#    provided with the distribution.
# 
# 3. The name Zope Corporation (tm) must not be used to
#    endorse or promote products derived from this software
#    without prior written permission from Zope Corporation.
# 
# 4. The right to distribute this software or to use it for
#    any purpose does not give you the right to use Servicemarks
#    (sm) or Trademarks (tm) of Zope Corporation. Use of them is
#    covered in a separate agreement (see
#    http://www.zope.com/Marks).
# 
# 5. If any files are modified, you must cause the modified
#    files to carry prominent notices stating that you changed
#    the files and the date of any change.
# 
# Disclaimer
# 
#   THIS SOFTWARE IS PROVIDED BY ZOPE CORPORATION ``AS IS''
#   AND ANY EXPRESSED OR IMPLIED WARRANTIES, INCLUDING, BUT
#   NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
#   AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN
#   NO EVENT SHALL ZOPE CORPORATION OR ITS CONTRIBUTORS BE
#   LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
#   EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
#   LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#   LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
#   HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
#   CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
#   OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#   SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
#   DAMAGE.
# 
# 
# This software consists of contributions made by Zope
# Corporation and many individuals on behalf of Zope
# Corporation.  Specific attributions are listed in the
# accompanying credits file.
# 
#############################################################################
"""TCPWatch, a connection forwarder and HTTP proxy for monitoring connections.

Requires Python 2.1 or above.

Revision information:
$Id: tcpwatch.py,v 1.9 2004/06/17 00:03:46 shane Exp $
"""

from __future__ import nested_scopes

VERSION = '1.3'
COPYRIGHT = (
    'TCPWatch %s Copyright 2001 Shane Hathaway, Zope Corporation'
    % VERSION)

import sys
import os
import socket
import asyncore
import getopt
from time import time, localtime


RECV_BUFFER_SIZE = 8192
show_cr = 0


#############################################################################
#
# Connection forwarder
#
#############################################################################


class ForwardingEndpoint (asyncore.dispatcher):
    """A socket wrapper that accepts and generates stream messages.
    """
    _dests = ()

    def __init__(self, conn=None):
        self._outbuf = []
        asyncore.dispatcher.__init__(self, conn)

    def set_dests(self, dests):
        """Sets the destination streams.
        """
        self._dests = dests

    def write(self, data):
        if data:
            self._outbuf.append(data)
            self.handle_write()

    def readable(self):
        return 1

    def writable(self):
        return not self.connected or len(self._outbuf) > 0

    def handle_connect(self):
        for d in self._dests:
            d.write('')  # A blank string means the socket just connected.

    def received(self, data):
        if data:
            for d in self._dests:
                d.write(data)

    def handle_read(self):
        data = self.recv(RECV_BUFFER_SIZE)
        self.received(data)

    def handle_write(self):
        if not self.connected:
            # Wait for a connection.
            return
        buf = self._outbuf
        while buf:
            data = buf.pop(0)
            if data:
                sent = self.send(data)
                if sent < len(data):
                    buf.insert(0, data[sent:])
                    break

    def handle_close (self):
        dests = self._dests
        self._dests = ()
        for d in dests:
            d.close()
        self.close()

    def handle_error(self):
        t, v = sys.exc_info()[:2]
        for d in self._dests:
            if hasattr(d, 'error'):
                d.error(t, v)
        self.handle_close()



class EndpointObserver:
    """Sends stream events to a ConnectionObserver.

    Streams don't distinguish sources, while ConnectionObservers do.
    This adapter adds source information to stream events.
    """

    def __init__(self, obs, from_client):
        self.obs = obs
        self.from_client = from_client

    def write(self, data):
        if data:
            self.obs.received(data, self.from_client)
        else:
            self.obs.connected(self.from_client)

    def close(self):
        self.obs.closed(self.from_client)

    def error(self, t, v):
        self.obs.error(self.from_client, t, v)



class ForwardedConnectionInfo:
    transaction = 1

    def __init__(self, connection_number, client_addr, server_addr=None):
        self.opened = time()
        self.connection_number = connection_number
        self.client_addr = client_addr
        self.server_addr = server_addr

    def dup(self):
        return ForwardedConnectionInfo(self.connection_number,
                                       self.client_addr,
                                       self.server_addr)



class ForwardingService (asyncore.dispatcher):

    _counter = 0

    def __init__(self, listen_host, listen_port, dest_host, dest_port,
                 observer_factory=None):
        self._obs_factory = observer_factory
        self._dest = (dest_host, dest_port)
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind((listen_host, listen_port))
        self.listen(5)

    def handle_accept(self):
        info = self.accept()
        if info:
            # Got a connection.
            conn, addr = info
            conn.setblocking(0)

            ep1 = ForwardingEndpoint()  # connects client to self
            ep2 = ForwardingEndpoint()  # connects self to server

            counter = self._counter + 1
            self._counter = counter
            factory = self._obs_factory
            if factory is not None:
                fci = ForwardedConnectionInfo(counter, addr, self._dest)
                obs = factory(fci)
                dests1 = (ep2, EndpointObserver(obs, 1))
                dests2 = (ep1, EndpointObserver(obs, 0))
            else:
                dests1 = (ep2,)
                dests2 = (ep1,)

            ep1.set_dests(dests1)
            ep2.set_dests(dests2)

            # Now everything is hooked up.  Let data pass.
            ep2.create_socket(socket.AF_INET, socket.SOCK_STREAM)
            ep1.set_socket(conn)
            ep1.connected = 1  # We already know the client connected.
            ep2.connect(self._dest)

    def handle_error(self):
        # Don't stop the server.
        import traceback
        traceback.print_exc()



class IConnectionObserver:

    def connected(from_client):
        """Called when the client or the server connects.
        """

    def received(data, from_client):
        """Called when the client or the server sends data.
        """

    def closed(from_client):
        """Called when the client or the server closes the channel.
        """

    def error(from_client, type, value):
        """Called when an error occurs in the client or the server channel.
        """


#############################################################################
#
# Basic abstract connection observer and stdout observer
#
#############################################################################


def escape(s):
    # XXX This might be a brittle trick. :-(
    return repr('"\'' + str(s))[4:-1]


class BasicObserver:

    continuing_line = -1  # Tracks when a line isn't finished.
    arrows = ('<==', '==>')

    def __init__(self):
        self._start = time()

    def _output_message(self, m, from_client):
        if self.continuing_line >= 0:
            self.write('\n')
            self.continuing_line = -1
        if from_client:
            who = 'client'
        else:
            who = 'server'

        t = time() - self._start
        min, sec = divmod(t, 60)
        self.write('[%02d:%06.3f - %s %s]\n' % (min, sec, who, m))
        self.flush()

    def connection_from(self, fci):
        if fci.server_addr is not None:
            self._output_message(
                '%s:%s forwarded to %s:%s' %
                (tuple(fci.client_addr) + tuple(fci.server_addr)), 1)
        else:
            self._output_message(
                'connection from %s:%s' %
                (tuple(fci.client_addr)), 1)

        if fci.transaction > 1:
            self._output_message(
                ('HTTP transaction #%d' % fci.transaction), 1)

    def connected(self, from_client):
        self._output_message('connected', from_client)

    def received(self, data, from_client):
        arrow = self.arrows[from_client]
        cl = self.continuing_line
        if cl >= 0:
            if cl != from_client:
                # Switching directions.
                self.write('\n%s' % arrow)
        else:
            self.write(arrow)

        if data.endswith('\n'):
            data = data[:-1]
            newline = 1
        else:
            newline = 0

        if not show_cr:
            data = data.replace('\r', '')
        lines = data.split('\n')
        lines = map(escape, lines)
        s = ('\n%s' % arrow).join(lines)
        self.write(s)

        if newline:
            self.write('\n')
            self.continuing_line = -1
        else:
            self.continuing_line = from_client
        self.flush()

    def closed(self, from_client):
        self._output_message('closed', from_client)

    def error(self, from_client, type, value):
        self._output_message(
            'connection error %s: %s' % (type, value), from_client)
    
    def write(self, s):
        raise NotImplementedError

    def flush(self):
        raise NotImplementedError
            

class StdoutObserver (BasicObserver):

    # __implements__ = IConnectionObserver

    def __init__(self, fci):
        BasicObserver.__init__(self)
        self.connection_from(fci)

    def write(self, s):
        sys.stdout.write(s)

    def flush(self):
        sys.stdout.flush()


# 'log_number' is a log file counter used for naming log files.
log_number = 0

def nextLogNumber():
    global log_number
    log_number = log_number + 1
    return log_number    


class RecordingObserver (BasicObserver):
    """Log request to a file.

    o Filenames mangle connection and transaction numbers from the
      ForwardedConnectionInfo passed as 'fci'.

    o Decorates an underlying observer, created via the passed 'sub_factory'.

    o Files are created in the supplied 'record_directory'.

    o Unless suppressed, log response and error to corresponding files.
    """
    _ERROR_SOURCES = ('Server', 'Client')

    # __implements__ = IConnectionObserver

    def __init__(self, fci, sub_factory, record_directory,
                 record_prefix='watch', record_responses=1, record_errors=1):
        self._log_number = nextLogNumber()
        self._decorated = sub_factory(fci)
        self._directory = record_directory
        self._prefix = record_prefix
        self._response = record_responses
        self._errors = record_errors

    def connected(self, from_client):
        """See IConnectionObserver.
        """
        self._decorated.connected(from_client)

    def received(self, data, from_client):
        """See IConnectionObserver.
        """
        if from_client or self._response:
            extension = from_client and 'request' or 'response'
            file = self._openForAppend(extension=extension)
            file.write(data)
            file.close()
        self._decorated.received(data, from_client)

    def closed(self, from_client):
        """See IConnectionObserver.
        """
        self._decorated.closed(from_client)

    def error(self, from_client, type, value):
        """See IConnectionObserver.
        """
        if self._errors:
            file = self._openForAppend(extension='errors')
            file.write('(%s) %s: %s\n' % (self._ERROR_SOURCES[from_client],
                                          type, value))
        self._decorated.error(from_client, type, value)

    def _openForAppend(self, extension):
        """Open a file with the given extension for appending.

        o File should be in the directory indicated by self._directory.

        o File should have a filename '<prefix>_<conn #>.<extension>'.
        """
        filename = '%s%04d.%s' % (self._prefix, self._log_number, extension)
        fqpath = os.path.join(self._directory, filename)
        return open(fqpath, 'a')


#############################################################################
#
# Tkinter GUI
#
#############################################################################


def setupTk(titlepart, config_info, colorized=1):
    """Starts the Tk application and returns an observer factory.
    """

    import Tkinter
    from ScrolledText import ScrolledText
    from Queue import Queue, Empty
    try:
        from cStringIO import StringIO
    except ImportError:
        from StringIO import StringIO

    startup_text = COPYRIGHT + ("""

Use your client to connect to the proxied port(s) then click
the list on the left to see the data transferred.

%s
""" % config_info)


    class TkTCPWatch (Tkinter.Frame):
        '''The tcpwatch top-level window.
        '''
        def __init__(self, master):
            Tkinter.Frame.__init__(self, master)
            self.createWidgets()
            # connections maps ids to TkConnectionObservers.
            self.connections = {}
            self.showingid = ''
            self.queue = Queue()
            self.processQueue()

        def createWidgets(self):
            listframe = Tkinter.Frame(self)
            listframe.pack(side=Tkinter.LEFT, fill=Tkinter.BOTH, expand=1)
            scrollbar = Tkinter.Scrollbar(listframe, orient=Tkinter.VERTICAL)
            self.connectlist = Tkinter.Listbox(
                listframe, yscrollcommand=scrollbar.set, exportselection=0)
            scrollbar.config(command=self.connectlist.yview)
            scrollbar.pack(side=Tkinter.RIGHT, fill=Tkinter.Y)
            self.connectlist.pack(
                side=Tkinter.LEFT, fill=Tkinter.BOTH, expand=1)
            self.connectlist.bind('<Button-1>', self.mouseListSelect)
            self.textbox = ScrolledText(self, background="#ffffff")
            self.textbox.tag_config("message", foreground="#000000")
            self.textbox.tag_config("client", foreground="#007700")
            self.textbox.tag_config(
                "clientesc", foreground="#007700", background="#dddddd")
            self.textbox.tag_config("server", foreground="#770000")
            self.textbox.tag_config(
                "serveresc", foreground="#770000", background="#dddddd")
            self.textbox.insert(Tkinter.END, startup_text, "message")
            self.textbox.pack(side='right', fill=Tkinter.BOTH, expand=1)
            self.pack(fill=Tkinter.BOTH, expand=1)

        def addConnection(self, id, conn):
            self.connections[id] = conn
            connectlist = self.connectlist
            connectlist.insert(Tkinter.END, id)

        def updateConnection(self, id, output):
            if id == self.showingid:
                textbox = self.textbox
                for data, style in output:
                    textbox.insert(Tkinter.END, data, style)

        def mouseListSelect(self, event=None):
            connectlist = self.connectlist
            idx = connectlist.nearest(event.y)
            sel = connectlist.get(idx)
            connections = self.connections
            if connections.has_key(sel):
                self.showingid = ''
                output = connections[sel].getOutput()
                self.textbox.delete(1.0, Tkinter.END)
                for data, style in output:
                    self.textbox.insert(Tkinter.END, data, style)
                self.showingid = sel

        def processQueue(self):
            try:
                if not self.queue.empty():
                    # Process messages for up to 1/4 second
                    from time import time
                    limit = time() + 0.25
                    while time() < limit:
                        try:
                            f, args = self.queue.get_nowait()
                        except Empty:
                            break
                        f(*args)
            finally:
                self.master.after(50, self.processQueue)


    class TkConnectionObserver (BasicObserver):
        '''A connection observer which shows captured data in a TCPWatch
        frame.  The data is mangled for presentation.
        '''
        # __implements__ = IConnectionObserver

        def __init__(self, frame, fci, colorized=1):
            BasicObserver.__init__(self)
            self._output = []  # list of tuples containing (text, style)
            self._frame = frame
            self._colorized = colorized
            t = localtime(fci.opened)
            if fci.transaction > 1:
                base_id = '%03d-%02d' % (
                    fci.connection_number, fci.transaction)
            else:
                base_id = '%03d' % fci.connection_number
            id = '%s (%02d:%02d:%02d)' % (base_id, t[3], t[4], t[5])
            self._id = id
            frame.queue.put((frame.addConnection, (id, self)))
            self.connection_from(fci)

        def write(self, s):
            output = [(s, "message")]
            self._output.extend(output)
            self._frame.queue.put(
                (self._frame.updateConnection, (self._id, output)))

        def flush(self):
            pass

        def received(self, data, from_client):
            if not self._colorized:
                BasicObserver.received(self, data, from_client)
                return

            if not show_cr:
                data = data.replace('\r', '')

            output = []

            extra_color = (self._colorized == 2)

            if extra_color:
                # 4 colors: Change the color client/server and escaped chars
                def append(ss, escaped, output=output,
                           from_client=from_client, escape=escape):
                    if escaped:
                        output.append((escape(ss), from_client
                                       and 'clientesc' or 'serveresc'))
                    else:
                        output.append((ss, from_client
                                       and 'client' or 'server'))
            else:
                # 2 colors: Only change color for client/server
                segments = []
                def append(ss, escaped, segments=segments,
                           escape=escape):
                    if escaped:
                        segments.append(escape(ss))
                    else:
                        segments.append(ss)

            # Escape the input data.
            was_escaped = 0
            start_idx = 0
            for idx in xrange(len(data)):
                c = data[idx]
                escaped = (c < ' ' and c != '\n') or c >= '\x80'
                if was_escaped != escaped:
                    ss = data[start_idx:idx]
                    if ss:
                        append(ss, was_escaped)
                    was_escaped = escaped
                    start_idx = idx
            ss = data[start_idx:]
            if ss:
                append(ss, was_escaped)

            if not extra_color:
                output.append((''.join(segments),
                               from_client and 'client' or 'server'))

            # Send output to the frame.
            self._output.extend(output)
            self._frame.queue.put(
                (self._frame.updateConnection, (self._id, output)))
            if data.endswith('\n'):
                self.continuing_line = -1
            else:
                self.continuing_line = from_client

        def getOutput(self):
            return self._output


    def createApp(titlepart):
        master = Tkinter.Tk()
        app = TkTCPWatch(master)
        try:
            wm_title = app.master.wm_title
        except AttributeError:
            pass  # No wm_title method available.
        else:
            wm_title('TCPWatch [%s]' % titlepart)
        return app

    app = createApp(titlepart)

    def tkObserverFactory(fci, app=app, colorized=colorized):
        return TkConnectionObserver(app, fci, colorized)

    return tkObserverFactory, app.mainloop



#############################################################################
#
# The HTTP splitter
#
# Derived from Zope.Server.HTTPServer.
#
#############################################################################


def find_double_newline(s):
    """Returns the position just after the double newline."""
    pos1 = s.find('\n\r\n')  # One kind of double newline
    if pos1 >= 0:
        pos1 += 3
    pos2 = s.find('\n\n')    # Another kind of double newline
    if pos2 >= 0:
        pos2 += 2

    if pos1 >= 0:
        if pos2 >= 0:
            return min(pos1, pos2)
        else:
            return pos1
    else:
        return pos2



class StreamedReceiver:
    """Accepts data up to a specific limit."""

    completed = 0

    def __init__(self, cl, buf=None):
        self.remain = cl
        self.buf = buf
        if cl < 1:
            self.completed = 1

    def received(self, data):
        rm = self.remain
        if rm < 1:
            self.completed = 1  # Avoid any chance of spinning
            return 0
        buf = self.buf
        datalen = len(data)
        if rm <= datalen:
            if buf is not None:
                buf.append(data[:rm])
            self.remain = 0
            self.completed = 1
            return rm
        else:
            if buf is not None:
                buf.append(data)
            self.remain -= datalen
            return datalen



class UnlimitedReceiver:
    """Accepts data without limits."""

    completed = 0

    def received(self, data):
        # always consume everything
        return len(data)



class ChunkedReceiver:
    """Accepts all chunks."""

    chunk_remainder = 0
    control_line = ''
    all_chunks_received = 0
    trailer = ''
    completed = 0


    def __init__(self, buf=None):
        self.buf = buf

    def received(self, s):
        # Returns the number of bytes consumed.
        if self.completed:
            return 0
        orig_size = len(s)
        while s:
            rm = self.chunk_remainder
            if rm > 0:
                # Receive the remainder of a chunk.
                to_write = s[:rm]
                if self.buf is not None:
                    self.buf.append(to_write)
                written = len(to_write)
                s = s[written:]
                self.chunk_remainder -= written
            elif not self.all_chunks_received:
                # Receive a control line.
                s = self.control_line + s
                pos = s.find('\n')
                if pos < 0:
                    # Control line not finished.
                    self.control_line = s
                    s = ''
                else:
                    # Control line finished.
                    line = s[:pos]
                    s = s[pos + 1:]
                    self.control_line = ''
                    line = line.strip()
                    if line:
                        # Begin a new chunk.
                        semi = line.find(';')
                        if semi >= 0:
                            # discard extension info.
                            line = line[:semi]
                        sz = int(line.strip(), 16)  # hexadecimal
                        if sz > 0:
                            # Start a new chunk.
                            self.chunk_remainder = sz
                        else:
                            # Finished chunks.
                            self.all_chunks_received = 1
                    # else expect a control line.
            else:
                # Receive the trailer.
                trailer = self.trailer + s
                if trailer[:2] == '\r\n':
                    # No trailer.
                    self.completed = 1
                    return orig_size - (len(trailer) - 2)
                elif trailer[:1] == '\n':
                    # No trailer.
                    self.completed = 1
                    return orig_size - (len(trailer) - 1)
                pos = find_double_newline(trailer)
                if pos < 0:
                    # Trailer not finished.
                    self.trailer = trailer
                    s = ''
                else:
                    # Finished the trailer.
                    self.completed = 1
                    self.trailer = trailer[:pos]
                    return orig_size - (len(trailer) - pos)
        return orig_size



class HTTPStreamParser:
    """A structure that parses the HTTP stream.
    """

    completed = 0    # Set once request is completed.
    empty = 0        # Set if no request was made.
    header_plus = ''
    chunked = 0
    content_length = 0
    body_rcv = None

    # headers is a mapping containing keys translated to uppercase
    # with dashes turned into underscores.

    def __init__(self, is_a_request):
        self.headers = {}
        self.is_a_request = is_a_request
        self.body_data = []

    def received(self, data):
        """Receives the HTTP stream for one request.

        Returns the number of bytes consumed.
        Sets the completed flag once both the header and the
        body have been received.
        """
        if self.completed:
            return 0  # Can't consume any more.
        datalen = len(data)
        br = self.body_rcv
        if br is None:
            # In header.
            s = self.header_plus + data
            index = find_double_newline(s)
            if index >= 0:
                # Header finished.
                header_plus = s[:index]
                consumed = len(data) - (len(s) - index)
                self.in_header = 0
                # Remove preceeding blank lines.
                header_plus = header_plus.lstrip()
                if not header_plus:
                    self.empty = 1
                    self.completed = 1
                else:
                    self.parse_header(header_plus)
                    if self.body_rcv is None or self.body_rcv.completed:
                        self.completed = 1
                return consumed
            else:
                # Header not finished yet.
                self.header_plus = s
                return datalen
        else:
            # In body.
            consumed = br.received(data)
            self.body_data.append(data[:consumed])
            if br.completed:
                self.completed = 1
            return consumed


    def parse_header(self, header_plus):
        """Parses the header_plus block of text.

        (header_plus is the headers plus the first line of the request).
        """
        index = header_plus.find('\n')
        if index >= 0:
            first_line = header_plus[:index]
            header = header_plus[index + 1:]
        else:
            first_line = header_plus
            header = ''
        self.first_line = first_line
        self.header = header

        lines = self.get_header_lines()
        headers = self.headers
        for line in lines:
            index = line.find(':')
            if index > 0:
                key = line[:index]
                value = line[index + 1:].strip()
                key1 = key.upper().replace('-', '_')
                headers[key1] = value
            # else there's garbage in the headers?

        if not self.is_a_request:
            # Check for a 304 response.
            parts = first_line.split()
            if len(parts) >= 2 and parts[1] == '304':
                # Expect no body.
                self.body_rcv = StreamedReceiver(0)

        if self.body_rcv is None:
            # Ignore the HTTP version and just assume
            # that the Transfer-Encoding header, when supplied, is valid.
            te = headers.get('TRANSFER_ENCODING', '')
            if te == 'chunked':
                self.chunked = 1
                self.body_rcv = ChunkedReceiver()
            if not self.chunked:
                cl = int(headers.get('CONTENT_LENGTH', -1))
                self.content_length = cl
                if cl >= 0 or self.is_a_request:
                    self.body_rcv = StreamedReceiver(cl)
                else:
                    # No content length and this is a response.
                    # We have to assume unlimited content length.
                    self.body_rcv = UnlimitedReceiver()


    def get_header_lines(self):
        """Splits the header into lines, putting multi-line headers together.
        """
        r = []
        lines = self.header.split('\n')
        for line in lines:
            if line.endswith('\r'):
                line = line[:-1]
            if line and line[0] in ' \t':
                r[-1] = r[-1] + line[1:]
            else:
                r.append(line)
        return r



class HTTPConnectionSplitter:
    """Makes a new observer for each HTTP subconnection and forwards events.
    """

    # __implements__ = IConnectionObserver
    req_index = 0
    resp_index = 0

    def __init__(self, sub_factory, fci):
        self.sub_factory = sub_factory
        self.transactions = []  # (observer, request_data, response_data)
        self.fci = fci
        self._newTransaction()

    def _newTransaction(self):
        fci = self.fci.dup()
        fci.transaction = len(self.transactions) + 1
        obs = self.sub_factory(fci)
        req = HTTPStreamParser(1)
        resp = HTTPStreamParser(0)
        self.transactions.append((obs, req, resp))

    def _mostRecentObs(self):
        return self.transactions[-1][0]

    def connected(self, from_client):
        self._mostRecentObs().connected(from_client)

    def closed(self, from_client):
        self._mostRecentObs().closed(from_client)

    def error(self, from_client, type, value):
        self._mostRecentObs().error(from_client, type, value)

    def received(self, data, from_client):
        transactions = self.transactions
        while data:
            if from_client:
                index = self.req_index
            else:
                index = self.resp_index
            if index >= len(transactions):
                self._newTransaction()

            obs, req, resp = transactions[index]
            if from_client:
                parser = req
            else:
                parser = resp

            consumed = parser.received(data)
            obs.received(data[:consumed], from_client)
            data = data[consumed:]
            if parser.completed:
                new_index = index + 1
                if from_client:
                    self.req_index = new_index
                else:
                    self.resp_index = new_index


#############################################################################
#
# HTTP proxy
#
#############################################################################


class HTTPProxyToServerConnection (ForwardingEndpoint):
    """Ensures that responses to a persistent HTTP connection occur
    in the correct order."""

    finished = 0

    def __init__(self, proxy_conn, dests=()):
        ForwardingEndpoint.__init__(self)
        self.response_parser = HTTPStreamParser(0)
        self.proxy_conn = proxy_conn
        self.set_dests(dests)

        # Data for the client held until previous responses are sent
        self.held = []

    def _isMyTurn(self):
        """Returns a true value if it's time for this response
        to respond to the client."""
        order = self.proxy_conn._response_order
        if order:
            return (order[0] is self)
        return 1

    def received(self, data):
        """Receives data from the HTTP server to be sent back to the client."""
        while 1:
            parser = self.response_parser
            if parser.completed:
                self.finished = 1
                self.flush()
                # Note that any extra data returned from the server is
                # ignored. Should it be? :-(
                return
            if not data:
                break
            consumed = parser.received(data)
            fragment = data[:consumed]
            data = data[consumed:]
            ForwardingEndpoint.received(self, fragment)
            self.held.append(fragment)
            self.flush()

    def flush(self):
        """Flushes buffers and, if the response has been sent, allows
        the next response to take over.
        """
        if self.held and self._isMyTurn():
            data = ''.join(self.held)
            del self.held[:]
            self.proxy_conn.write(data)
        if self.finished:
            order = self.proxy_conn._response_order
            if order and order[0] is self:
                del order[0]
            if order:
                order[0].flush()  # kick!

    def handle_close(self):
        """The HTTP server closed the connection.
        """
        ForwardingEndpoint.handle_close(self)
        if not self.finished:
            # Cancel the proxy connection, even if there are responses
            # pending, since the HTTP spec provides no way to recover
            # from an unfinished response.
            self.proxy_conn.close()

    def close(self):
        """Close the connection to the server.

        If there is unsent response data, an error is generated.
        """
        self.flush()
        if not self.finished:
            t = IOError
            v = 'Closed without finishing response to client'
            for d in self._dests:
                if hasattr(d, 'error'):
                    d.error(t, v)
        ForwardingEndpoint.close(self)



class HTTPProxyToClientConnection (ForwardingEndpoint):
    """A connection from a client to the proxy server"""

    _req_parser = None
    _transaction = 0
    _obs = None

    def __init__(self, conn, factory, counter, addr):
        ForwardingEndpoint.__init__(self, conn)
        self._obs_factory = factory
        self._counter = counter
        self._client_addr = addr
        self._response_order = []
        self._newRequest()

    def _newRequest(self):
        """Starts a new request on a persistent connection."""
        if self._req_parser is None:
            self._req_parser = HTTPStreamParser(1)
        factory = self._obs_factory
        if factory is not None:
            fci = ForwardedConnectionInfo(self._counter, self._client_addr)
            self._transaction = self._transaction + 1
            fci.transaction = self._transaction
            obs = factory(fci)
            self._obs = obs
            self.set_dests((EndpointObserver(obs, 1),))

    def received(self, data):
        """Accepts data received from the client."""
        while data:
            parser = self._req_parser
            if parser is None:
                # Begin another request.
                self._newRequest()
                parser = self._req_parser
            if not parser.completed:
                # Waiting for a complete request.
                consumed = parser.received(data)
                ForwardingEndpoint.received(self, data[:consumed])
                data = data[consumed:]
            if parser.completed:
                # Connect to a server.
                self.openProxyConnection(parser)
                # Expect a new request or a closed connection.
                self._req_parser = None

    def openProxyConnection(self, request):
        """Parses the client connection and opens a connection to an
        HTTP server.
        """
        first_line = request.first_line.strip()
        if not ' ' in first_line:
            raise ValueError, ('Malformed request: %s' % first_line)
        command, url = first_line.split(' ', 1)
        pos = url.rfind(' HTTP/')
        if pos >= 0:
            protocol = url[pos + 1:]
            url = url[:pos].rstrip()
        else:
            protocol = 'HTTP/1.0'
        if url.startswith('http://'):
            # Standard proxy
            urlpart = url[7:]
            if '/' in urlpart:
                host, path = url[7:].split('/', 1)
                path = '/' + path
            else:
                host = urlpart
                path = '/'
        else:
            # Transparent proxy
            host = request.headers.get('HOST')
            path = url
        if not host:
            raise ValueError, ('Request type not supported: %s' % url)

        if ':' in host:
            host, port = host.split(':')
            port = int(port)
        else:
            port = 80

        if '@' in host:
            username, host = host.split('@')

        obs = self._obs
        if obs is not None:
            eo = EndpointObserver(obs, 0)
            ptos = HTTPProxyToServerConnection(self, (eo,))
        else:
            ptos = HTTPProxyToServerConnection(self)

        self._response_order.append(ptos)

        ptos.write('%s %s %s\r\n' % (command, path, protocol))
        # Duplicate the headers sent by the client.
        if request.header:
            ptos.write(request.header)
        else:
            ptos.write('\r\n')
        if request.body_data:
            ptos.write(''.join(request.body_data))
        ptos.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        ptos.connect((host, port))

    def close(self):
        """Closes the connection to the client.

        If there are open connections to proxy servers, the server
        connections are also closed.
        """
        ForwardingEndpoint.close(self)
        for ptos in self._response_order:
            ptos.close()
        del self._response_order[:]


class HTTPProxyService (asyncore.dispatcher):
    """A minimal HTTP proxy server"""

    connection_class = HTTPProxyToClientConnection

    _counter = 0

    def __init__(self, listen_host, listen_port, observer_factory=None):
        self._obs_factory = observer_factory
        asyncore.dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind((listen_host, listen_port))
        self.listen(5)

    def handle_accept(self):
        info = self.accept()
        if info:
            # Got a connection.
            conn, addr = info
            conn.setblocking(0)
            counter = self._counter + 1
            self._counter = counter
            self.connection_class(conn, self._obs_factory, counter, addr)

    def handle_error(self):
        # Don't stop the server.
        import traceback
        traceback.print_exc()


#############################################################################
#
# Command-line interface
#
#############################################################################

def usage():
    sys.stderr.write(COPYRIGHT + '\n')
    sys.stderr.write(
        """TCP monitoring and logging tool with support for HTTP 1.1
Simple usage: tcpwatch.py -L listen_port:dest_hostname:dest_port

TCP forwarded connection setup:
  -L <listen_port>:<dest_port>
     Set up a local forwarded connection
  -L <listen_port>:<dest_host>:<dest_port>
     Set up a forwarded connection to a specified host
  -L <listen_host>:<listen_port>:<dest_host>:<dest_port>
     Set up a forwarded connection to a specified host, bound to an interface

HTTP setup:
  -h (or --http) Split forwarded HTTP persistent connections
  -p [<listen_host>:]<listen_port> Run an HTTP proxy

Output options:
  -s   Output to stdout instead of a Tkinter window
  -n   No color in GUI (faster and consumes less RAM)
  -c   Extra color (colorizes escaped characters)
  --cr     Show carriage returns (ASCII 13)
  --help   Show usage information

Recording options:
  -r <path>  (synonyms: -R, --record-directory)
    Write recorded data to <path>.  By default, creates request and
    response files for each request, and writes a corresponding error file
    for any error detected by tcpwatch.
  --record-prefix=<prefix>
    Use <prefix> as the file prefix for logged request / response / error
    files (defaults to 'watch').
  --no-record-responses
    Suppress writing '.response' files.
  --no-record-errors
    Suppress writing '.error' files.
""")
    sys.exit()


def usageError(s):
    sys.stderr.write(str(s) + '\n\n')
    usage()


def main(args):
    global show_cr

    try:
        optlist, extra = getopt.getopt(args, 'chL:np:r:R:s',
                                       ['help', 'http', 'cr',
                                        'record-directory=',
                                        'record-prefix=',
                                        'no-record-responses',
                                        'no-record-errors',
                                       ])
    except getopt.GetoptError, msg:
        usageError(msg)

    fwd_params = []
    proxy_params = []
    obs_factory = None
    show_config = 0
    split_http = 0
    colorized = 1
    record_directory = None
    record_prefix = 'watch'
    record_responses = 1
    record_errors = 1
    recording = {}

    for option, value in optlist:
        if option == '--help':
            usage()
        elif option == '--http' or option == '-h':
            split_http = 1
        elif option == '-n':
            colorized = 0
        elif option == '-c':
            colorized = 2
        elif option == '--cr':
            show_cr = 1
        elif option == '-s':
            show_config = 1
            obs_factory = StdoutObserver
        elif option == '-p':
            # HTTP proxy
            info = value.split(':')
            listen_host = ''
            if len(info) == 1:
                listen_port = int(info[0])
            elif len(info) == 2:
                listen_host = info[0]
                listen_port = int(info[1])
            else:
                usageError('-p requires a port or a host:port parameter')
            proxy_params.append((listen_host, listen_port))
        elif option == '-L':
            # TCP forwarder
            info = value.split(':')
            listen_host = ''
            dest_host = ''
            if len(info) == 2:
                listen_port = int(info[0])
                dest_port = int(info[1])
            elif len(info) == 3:
                listen_port = int(info[0])
                dest_host = info[1]
                dest_port = int(info[2])
            elif len(info) == 4:
                listen_host = info[0]
                listen_port = int(info[1])
                dest_host = info[2]
                dest_port = int(info[3])
            else:
                usageError('-L requires 2, 3, or 4 colon-separated parameters')
            fwd_params.append(
                (listen_host, listen_port, dest_host, dest_port))
        elif (option == '-r'
              or option == '-R'
              or option == '--record-directory'):
            record_directory = value
        elif option == '--record-prefix':
            record_prefix = value
        elif option == '--no-record-responses':
            record_responses = 0
        elif option == '--no-record-errors':
            record_errors = 0

    if not fwd_params and not proxy_params:
        usageError("At least one -L or -p option is required.")

    # Prepare the configuration display.
    config_info_lines = []
    title_lst = []
    if fwd_params:
        config_info_lines.extend(map(
            lambda args: 'Forwarding %s:%d -> %s:%d' % args, fwd_params))
        title_lst.extend(map(
            lambda args: '%s:%d -> %s:%d' % args, fwd_params))
    if proxy_params:
        config_info_lines.extend(map(
            lambda args: 'HTTP proxy listening on %s:%d' % args, proxy_params))
        title_lst.extend(map(
            lambda args: '%s:%d -> proxy' % args, proxy_params))
    if split_http:
        config_info_lines.append('HTTP connection splitting enabled.')
    if record_directory:
        config_info_lines.append(
            'Recording to directory %s.' % record_directory)
    config_info = '\n'.join(config_info_lines)
    titlepart = ', '.join(title_lst)
    mainloop = None

    if obs_factory is None:
        # If no observer factory has been specified, use Tkinter.
        obs_factory, mainloop = setupTk(titlepart, config_info, colorized)

    if record_directory:
        def _decorateRecorder(fci, sub_factory=obs_factory,
                              record_directory=record_directory,
                              record_prefix=record_prefix,
                              record_responses=record_responses,
                              record_errors=record_errors):
            return RecordingObserver(fci, sub_factory, record_directory,
                                     record_prefix, record_responses,
                                     record_errors)
        obs_factory = _decorateRecorder

    chosen_factory = obs_factory
    if split_http:
        # Put an HTTPConnectionSplitter between the events and the output.
        def _factory(fci, sub_factory=obs_factory):
            return HTTPConnectionSplitter(sub_factory, fci)
        chosen_factory = _factory
    # obs_factory is the connection observer factory without HTTP
    # connection splitting, while chosen_factory may have connection
    # splitting.  Proxy services use obs_factory rather than the full
    # chosen_factory because proxy services perform connection
    # splitting internally.

    services = []
    try:
        # Start forwarding services.
        for params in fwd_params:
            args = params + (chosen_factory,)
            s = ForwardingService(*args)
            services.append(s)

        # Start proxy services.
        for params in proxy_params:
            args = params + (obs_factory,)
            s = HTTPProxyService(*args)
            services.append(s)

        if show_config:
            sys.stderr.write(config_info + '\n')

        # Run the main loop.
        try:
            if mainloop is not None:
                import thread
                thread.start_new_thread(asyncore.loop, (), {'timeout': 1.0})
                mainloop()
            else:
                asyncore.loop(timeout=1.0)
        except KeyboardInterrupt:
            sys.stderr.write('TCPWatch finished.\n')
    finally:
        for s in services:
            s.close()

def run_main():
    """Setuptools entry point for console script
    """
    main(sys.argv[1:])

if __name__ == '__main__':
    main(sys.argv[1:])
