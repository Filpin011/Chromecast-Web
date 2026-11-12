import time
import pychromecast
import zeroconf


class ChromecastWeb:
    def __init__(self):
        self.name = "Chromecast"
        self.chromecast=None
        self.volume = 1.0
        self.status = "Not connected"
        self.duration = 0
        self.current_time = 0
        self.title = "Unknown"
        self.content_type = "Unknown"
        self.zconf = zeroconf.Zeroconf()
        self.browser = pychromecast.CastBrowser(pychromecast.SimpleCastListener(), self.zconf)


    

    def connect_to_chromecast(self, device_name):
        """Connects to the selected Chromecast."""
        global selected_chromecast
        chromecasts, _ = pychromecast.get_listed_chromecasts(friendly_names=[device_name])

        if not chromecasts:
            self.chromecast= None

        selected_chromecast = chromecasts[0]
        selected_chromecast.wait()
        self.chromecast= selected_chromecast

    def get_chromecast_devices(self):
        """Returns a list of Chromecast devices."""

        self.browser.start_discovery()
        time.sleep(5)
        self.browser.stop_discovery()

        return self.browser.devices.keys()
    
    def update_chromecast_status(self):
        """Returns Chromecast playback status."""
        if not self.chromecast:
            return {"status": "Not connected"}

        mc = self.chromecast.media_controller
        self.status = mc.status
        self.title = self.status.title or "Unknown"
        self.content_type = self.status.content_type or "Unknown"
        self.duration = self.status.duration or 0
        self.current_time = self.status.current_time or 0
        self.volume = self.chromecast.status.volume_level

        

    def get_chromecast_status(self):
        self.update_chromecast_status()
        return {
            "status": self.status,
            "title": self.title,
            "content_type": self.content_type,
            "duration": self.duration,
            "current_time": self.current_time,
            "volume": self.volume
        }
    
    def display_image_on_chromecast(self, static_image_url):
        """Displays a static image on Chromecast."""
        if not self.chromecast:
            return "Chromecast not connected."

        mc = self.chromecast.media_controller
        mc.play_media(static_image_url, "image/jpeg")
        mc.block_until_active()
        return "Static image displayed on Chromecast."
    
    def stop_stream(self):
        if not self.chromecast:
            return "Chromecast not connected."

        mc = self.chromecast.media_controller
        mc.stop()
        return "Streaming stopped on Chromecast."