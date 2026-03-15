"""Vulnerable: Unsafe deserialization via pickle and yaml."""

import pickle

import yaml
from flask import Flask, request

app = Flask(__name__)


@app.route("/load", methods=["POST"])
def load_object():
    data = request.get_data()
    # pickle.loads on untrusted input = remote code execution
    obj = pickle.loads(data)
    return str(obj)


@app.route("/config", methods=["POST"])
def load_config():
    raw = request.get_data(as_text=True)
    # yaml.load without SafeLoader = code execution
    config = yaml.load(raw)
    return str(config)


def process_cached(cache_file: str):
    with open(cache_file, "rb") as f:
        return pickle.load(f)
