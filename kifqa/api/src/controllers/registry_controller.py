from flask import jsonify
from src.services.registry_service import  get_model


def model():
    model = get_model()

    if model:
        return jsonify({"model": True})
    else:
        return jsonify({"model": False})
