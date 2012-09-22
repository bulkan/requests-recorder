import SocketServer
import json
import cgi
import SimpleHTTPServer
from urlparse import urlparse
import signal
from urllib import urlencode

import requests


PORT = 8000

log = open("log.out", "w")


def write_request(method, headers, path, data=None):
    """ write the request to the file """
    request = {"method": method,
            "headers": headers,
            "path": path,
            "data": data
            }

    log.write(json.dumps(request))
    log.write("\n")


class Proxy(SimpleHTTPServer.SimpleHTTPRequestHandler):
    def do_GET(self):
        (scm, netloc, path, params, query, fragment) = urlparse(
            self.path, 'http')
        self.log_request()
        write_request("GET", self.headers.items(), self.path)
        resp = requests.get(self.path, headers=self.headers)
        self.wfile.write(resp.content)

    def do_POST(self):
        self.log_request()
        #from StringIO import StringIO
        #d = StringIO(self.rfile.read())
        headers = dict(self.headers.items())
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=headers,
            environ={'REQUEST_METHOD': 'POST',
                     'CONTENT_TYPE': headers['content-type'],
             })

        data = dict([(i.name, i.value) for i in form.list])
        #write_request("POST", self.headers.items(), self.path, data=data)

        #if 'proxy-connection' in headers:
            #del headers['proxy-connection']

        if 'content-length' in headers:
            del headers['content-length']

        #headers = {'cookie': headers.get("cookie"),
                   #'content-type': headers.get('content-type')}

        resp = requests.post(self.path, headers=headers, data=urlencode(data))
        #for d in resp.content.read(100):
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
