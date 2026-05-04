#!/usr/bin/env python3
"""Robust local static server for the reunion preview.

Handles BrokenPipe / ConnectionReset gracefully (browsers cancel range
requests on large videos all the time; default http.server crashes the
request thread, which can cascade and break recordings).

Adds Range support fallback handling and HEAD request quietness.

Usage:  cd project && python3 serve.py [PORT]
"""
import http.server
import socketserver
import sys
import os
from http import HTTPStatus

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    # Slightly longer write buffer for video files
    wbufsize = 1 << 20

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Browser canceled mid-stream (range-request abort, scrub, tab close).
            # Not a real error.
            pass

    def copyfile(self, src, dst):
        try:
            super().copyfile(src, dst)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, fmt, *args):
        # Quieter logging — only print real errors, not every GET
        msg = fmt % args
        if args and isinstance(args[0], str) and args[0].startswith(('GET', 'HEAD')):
            code = args[1] if len(args) > 1 else ''
            if str(code).startswith(('2', '3')):
                return  # don't log success
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), msg))


# Allow port reuse on rapid restarts
class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        """Silently swallow client-disconnect exceptions (browser cancels
        range requests on large videos all the time; not a real error)."""
        import traceback
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        # Real errors still printed
        sys.stderr.write("[server-error] from %s\n" % (client_address,))
        traceback.print_exc(file=sys.stderr)


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"Serving {os.getcwd()} at http://localhost:{PORT}/")
    print(f"Open: http://localhost:{PORT}/reunion_full.html")
    with ReusableTCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nshutting down")
