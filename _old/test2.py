import subprocess
import http.server
import socketserver

# Configuration
STREAM_URL = "https://top1-cdnnew.iosplayer.ru/top1-cdn/calcioXserie/mono.m3u8"  # Replace with your HLS URL
LOCAL_SERVER_PORT = 8080
FFMPEG_PORT = 9999  # FFmpeg sends MPEG-TS here

def start_ffmpeg():
    """Start FFmpeg to restream the HLS feed as an MPEG-TS stream."""
    cmd = [
        "ffmpeg",
        "-i", STREAM_URL,
        "-c:v", "copy", "-c:a", "copy",
        "-f", "mpegts",
        f"udp://127.0.0.1:{FFMPEG_PORT}"  # Streaming to local UDP port
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class TSRequestHandler(http.server.BaseHTTPRequestHandler):
    """Serve the MPEG-TS stream over HTTP."""
    def do_GET(self):
        if self.path == "/stream.ts":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.end_headers()

            # Read data from FFmpeg and send it to the client
            with socketserver.socket.socket(socketserver.socket.AF_INET, socketserver.socket.SOCK_DGRAM) as sock:
                sock.bind(("127.0.0.1", FFMPEG_PORT))
                while True:
                    data, _ = sock.recvfrom(4096)  # Read MPEG-TS data
                    self.wfile.write(data)  # Send it to the HTTP client
        else:
            self.send_response(404)
            self.end_headers()

def start_http_server():
    """Start a simple HTTP server to serve the MPEG-TS stream."""
    with socketserver.TCPServer(("", LOCAL_SERVER_PORT), TSRequestHandler) as httpd:
        print(f"Serving MPEG-TS at http://localhost:{LOCAL_SERVER_PORT}/stream.ts")
        httpd.serve_forever()

if __name__ == "__main__":
    ffmpeg_process = start_ffmpeg()
    try:
        start_http_server()
    except KeyboardInterrupt:
        print("Stopping stream...")
        ffmpeg_process.terminate()
