from flask import jsonify


def status():
    return jsonify({'status': 200})
