import time
import pychromecast

WEB_PAGE_URL = "http://192.168.1.139:8080/index.html"  # Change this to your actual hosted page

def cast_webpage_keep_alive(chromecast_name):
    # Discover and connect to Chromecast
    chromecasts, browser = pychromecast.get_listed_chromecasts(friendly_names=[chromecast_name])

    if not chromecasts:
        print(f"Chromecast '{chromecast_name}' not found.")
        return
    
    cast_device = chromecasts[0]
    cast_device.wait()

    print(f"Connected to {chromecast_name}. Loading web page...")
    
    # Load web page using the built-in Chromecast browser
    cast_device.quit_app()  # Ensure a fresh start
    time.sleep(2)  # Wait for Chromecast to reset
    cast_device.start_app("E8C28D3C")  # Load the default Chromecast receiver
    time.sleep(2)

    # Use the Chromecast browser to open the page
    cast_device.media_controller.play_media(WEB_PAGE_URL, "text/html")
    cast_device.media_controller.block_until_active()

    # Keep connection alive
    try:
        while True:
            status = cast_device.status
            print(f"Chromecast Status: {status}")

            # If Chromecast stops, restart it
            if not cast_device.media_controller.is_playing:
                print("Stream stopped. Restarting...")
                cast_device.media_controller.play_media(WEB_PAGE_URL, "text/html")

            time.sleep(10)  # Check every 10 seconds
    except KeyboardInterrupt:
        print("Stopping the Chromecast connection.")
    finally:
        browser.stop_discovery()

if __name__ == "__main__":
    cast_webpage_keep_alive("Salotto")  # Change to your Chromecast name
