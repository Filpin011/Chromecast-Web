from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import pychromecast
import zeroconf
import time
import re
from playwright.sync_api import sync_playwright

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Store Chromecast instance
selected_chromecast = None
static_image_url = "https://wallpapers.com/images/hd/google-background-kb0l939oslmk9bss.jpg"  # Change to your preferred image


def get_hls_url(page_url):
    """Uses Playwright to find an HLS (.m3u8) URL in a dynamically loaded webpage."""
    try:

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(page_url, wait_until="networkidle")

            # Extract .m3u8 URLs
            matches = re.findall(r'https?://[^\s"\']+\.m3u8', page.content())
            browser.close()

            return matches[0] if matches else None
    except Exception as e:
        return None

def get_chromecast_devices():
    """Returns a list of available Chromecast devices."""
    devices = []
    zconf = zeroconf.Zeroconf()
    browser = pychromecast.CastBrowser(
        pychromecast.SimpleCastListener(lambda uuid, service: devices.append(browser.devices[uuid].friendly_name)), zconf
    )

    browser.start_discovery()
    time.sleep(5)  # Wait for devices to be discovered
    browser.stop_discovery()

    return devices

def connect_to_chromecast(device_name):
    """Connects to the selected Chromecast."""
    global selected_chromecast
    chromecasts, _ = pychromecast.get_listed_chromecasts(friendly_names=[device_name])

    if not chromecasts:
        return None

    selected_chromecast = chromecasts[0]
    selected_chromecast.wait()
    return selected_chromecast

def get_chromecast_status():
    """Returns Chromecast playback status."""
    global selected_chromecast
    if not selected_chromecast:
        return {"status": "Not connected"}

    mc = selected_chromecast.media_controller
    status = mc.status

    return {
        "status": status.player_state,
        "title": status.title or "Unknown",
        "content_type": status.content_type or "Unknown",
        "duration": status.duration or 0,
        "current_time": status.current_time or 0,
        "volume": selected_chromecast.status.volume_level
    }

def display_image_on_chromecast():
    """Displays a static image on Chromecast."""
    global selected_chromecast, static_image_url
    if not selected_chromecast:
        return "Chromecast not connected."

    mc = selected_chromecast.media_controller
    mc.play_media(static_image_url, "image/jpeg")
    mc.block_until_active()
    return "Static image displayed on Chromecast."

def cast_to_chromecast(hls_url):
    """Streams the HLS URL to Chromecast."""
    global selected_chromecast
    if not selected_chromecast:
        return "Chromecast not connected."

    mc = selected_chromecast.media_controller
    mc.play_media(hls_url,"video/mp2t", stream_type='LIVE')
    return "Streaming started on Chromecast."

def stop_stream():
    """Stops the current stream and restores the static image."""
    global selected_chromecast, static_image_url
    if not selected_chromecast:
        return "Chromecast not connected."

    return selected_chromecast.disconnect()

def refresh():
    """Force to seek to the end of the stream."""
    global selected_chromecast
    if not selected_chromecast:
        return "Chromecast not connected."

    mc = selected_chromecast.media_controller
    mc.play()
    return "Refreshed"

@app.route("/")
def index():
    """Render the web UI."""
    return render_template("index.html")

@app.route("/search-chromecast", methods=["GET"])
def search_chromecast():
    """Returns a list of available Chromecast devices."""
    devices = get_chromecast_devices()
    return jsonify({"devices": devices})

@app.route("/connect-chromecast", methods=["POST"])
def connect_chromecast():
    """Connects to the selected Chromecast and shows a static image."""
    data = request.json
    device_name = data.get("device_name")

    if connect_to_chromecast(device_name):
        display_image_on_chromecast()
        return jsonify({"message": f"Connected to {device_name} and displaying image."})
    else:
        return jsonify({"error": "Chromecast not found."}), 400

@app.route("/cast", methods=["POST"])
def cast():
    """Starts streaming the extracted HLS URL to Chromecast."""
    data = request.json
    hls_url = data.get("hls_url")

    result = cast_to_chromecast(hls_url)
    return jsonify({"message": result})

@app.route("/stop", methods=["POST"])
def stop():
    """Stops the stream and restores the image."""
    result = stop_stream()
    return jsonify({"message": result})

@app.route("/extract-hls", methods=["POST"])
def extract_hls():
    """Extracts an HLS URL from a given website URL."""
    data = request.json
    website_url = data.get("website_url")
    
    hls_url = get_hls_url(website_url)
    if hls_url:
        return jsonify({"hls_url": hls_url})
    else:
        return jsonify({"error": "No HLS stream found."}), 400
    
@app.route("/refresh", methods=["POST"])
def refresh_stream():
    """Refresh the stream."""
    result = refresh()
    return jsonify({"message": result})

@app.route("/status", methods=["GET"])
def status():
    """Fetches current Chromecast status."""
    return jsonify(get_chromecast_status())

@socketio.on("request_status")
def handle_request_status():
    """Sends real-time Chromecast status to clients."""
    while True:
        socketio.emit("update_status", get_chromecast_status())
        socketio.sleep(2)  # Update every 2 seconds



if __name__ == "__main__":
    socketio.run(app, debug=True)
