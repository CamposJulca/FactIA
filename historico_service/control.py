import json
import os

CONTROL_FILE = "procesados.json"

def load_processed():
    if os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE, "r") as f:
            return json.load(f)
    return {}

def save_processed(data):
    with open(CONTROL_FILE, "w") as f:
        json.dump(data, f, indent=4)