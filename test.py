import pychromecast
import ffmpeg
import subprocess
import time

import zeroconf
from collections import deque

# Function to start streaming to Chromecast
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
def stream_to_chromecast(hls_url, chromecast_name):
    # Step 1: Discover Chromecast
    get_chromecast_devices()
    cast_device=connect_to_chromecast(chromecast_name)
    print(f"Connected to Chromecast: {chromecast_name}")

    # Step 2: Set up FFmpeg to capture the HLS stream and transcode it
    # FFmpeg command to convert HLS stream to MP4 (or other formats if needed)
    try:
        # Create an FFmpeg input from the HLS URL
        stream = ffmpeg.input(hls_url)
        
        # Transcode the stream to MP4 format
        output = ffmpeg.output(stream, 'pipe:1', format='mp4', vcodec='libx264', acodec='aac', movflags='frag_keyframe+empty_moov')
        
        # Run the FFmpeg command and capture the output in real time
        process = output.run_async(pipe_stdout=True, pipe_stderr=True)

        # Step 3: Stream the transcoded data to Chromecast
        media_controller = cast_device.media_controller

        # Queue to store video chunks
        video_queue = deque()
        while True:
            # Read data from FFmpeg's stdout (transcoded video)
            data = process.stdout.read(1024 * 1024)  # 1 MB chunks
            if not data:
                break

            # Add data chunk to the queue
            video_queue.append(data)

            # If we have a chunk ready to send, send it to Chromecast
            if len(video_queue) > 0:
                chunk = video_queue.popleft()
                media_controller.play_media(chunk, 'video/mp4')  # Adjust MIME type if needed

            # Sleep to give Chromecast time to process and avoid overloading
            time.sleep(0.1)

    except Exception as e:
        print(f"Error while transcoding or streaming: {e}")

    # Step 4: Close the FFmpeg process
    process.stdout.close()
    process.wait()

    print("Stream finished.")

# Example usage
hls_url = "https://top1-cdnnew.iosplayer.ru/top1-cdn/calcioXserie/mono.m3u8"  # Replace with your HLS stream URL
chromecast_name = "Salotto"  # Replace with your Chromecast device's friendly name

# Start streaming to Chromecast
stream_to_chromecast(hls_url, chromecast_name)
