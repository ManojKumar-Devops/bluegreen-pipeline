from flask import Flask, jsonify
import os, socket

app = Flask(__name__)
VERSION = os.getenv("APP_VERSION", "2.0.0")

@app.route("/")
def home():
    return jsonify({
        "message": "Blue/Green Deployment Demo",
        "version": VERSION,
        "host": socket.gethostname(),
        "env": os.getenv("APP_ENV", "dev")
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)