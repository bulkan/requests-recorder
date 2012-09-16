import SocketServer

import SimpleHTTPServer
from urlparse import urlparse
import signal
import urllib
import requests


PORT = 8000


class Proxy(SimpleHTTPServer.SimpleHTTPRequestHandler):
    def do_GET(self):
        (scm, netloc, path, params, query, fragment) = urlparse(
            self.path, 'http')
        print self.path
        resp = requests.get(self.path)
        #print type(resp.raw)
        #print dir(resp.raw):
        #self.copyfile(resp.raw, self.wfile)
        self.wfile.write(resp.content)


SocketServer.ThreadingTCPServer.allow_reuse_address = True
httpd = SocketServer.ThreadingTCPServer(('localhost', PORT), Proxy)
httpd.daemon_threads = True


def handler(signo, frame):
    if signo == signal.SIGINT:
        print 'shutting down server'
        httpd.server_close()


signal.signal(signal.SIGINT, handler)


def main():
    print "serving at port", PORT

    httpd.serve_forever()


if __name__ == "__main__":
    main()
