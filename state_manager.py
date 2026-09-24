import json
import os

STATE_FILE = "sync_state.json"

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

class StateManager:
    def __init__(self):
        self.state = load_state()

    def get(self, key):
        return self.state.get(key)

    def set(self, key, value):
        self.state[key] = value
        save_state(self.state)