import json
import os

SETTINGS_FILE = ".editor_settings.json"
EDITION = "FREE"  # Change to "PRO" to unlock all features

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "last_source_directory": "./dummy_data",
        "last_export_path": "prompts.txt",
        "comfyui_url": "127.0.0.1:8188",
        "comfyui_workflow_path": "workflow_api.json"
    }

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)
    except Exception:
        pass
