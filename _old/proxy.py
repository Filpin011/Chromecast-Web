import requests
from flask import Flask, request, Response

app = Flask(__name__)

# Proxy endpoint to fetch HLS stream
@app.route('/proxy')
def proxy():
    # Get the URL of the HLS stream from the query parameters
    url = request.args.get('url')
    
    # If the URL is not provided, return a bad request error
    if not url:
        return "Missing URL parameter", 400

    try:
        # Make the GET request to fetch the HLS stream
        response = requests.get(url, stream=True)
        
        # Check if the request was successful
        if response.status_code == 200:
            # Pipe the content of the HLS stream back to the client
            return Response(response.iter_content(chunk_size=8192), content_type=response.headers['Content-Type'])

        else:
            return f"Error fetching the stream: {response.status_code}", 500
    except requests.exceptions.RequestException as e:
        # If any error occurs, return a 500 error
        return f"Error fetching the stream: {e}", 500

# Run the server on localhost:5000
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5555)
