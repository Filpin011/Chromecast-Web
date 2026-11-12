from flask import Flask, render_template, request, jsonify
from modules.web import ChromecastWeb

app = Flask(__name__)
chromecast = ChromecastWeb()

@app.route('/')
def index():
    return render_template('settings.html')

@app.route('/api/get_settings', methods=['GET'])
def get_settings():
    devices = chromecast.get_chromecast_devices()
    return jsonify(devices=devices)

@app.route('/api/set_chromecast', methods=['POST'])
def set_chromecast():
    data = request.json
    name = data.get('name')
    chromecast.connect_to_chromecast(name)
    return jsonify(message=f"Connected to {name}")

@app.route('/api/search_devices', methods=['GET'])
def search_devices():
    devices = chromecast.get_chromecast_devices()
    devices = [
        {
            "services": device.services,
            "uuid": device.uuid,
            "model_name": device.model_name,
            "friendly_name": device.friendly_name,
            "host": device.host,
            "port": device.port,
            "cast_type": device.cast_type,
            "manufacturer": device.manufacturer,
        }
        for device in devices
    ]
    return jsonify(devices=devices)

@app.route('/api/connect_chromecast', methods=['POST'])
def connect_chromecast():
    data = request.json
    name = data.get('name')
    chromecast.connect_to_chromecast(name)
    return jsonify(message=f"Connected to {name}")

if __name__ == "__main__":
    app.run(debug=True)