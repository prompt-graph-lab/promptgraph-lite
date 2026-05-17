import json
import os
from datetime import datetime, timezone

SETTINGS_FILE = ".editor_settings.json"
EDITION = "FREE"  # Change to "PRO" to unlock all features
MAX_RECENT_PROJECTS = 10


def _default_settings():
    return {
        "last_source_directory": "./dummy_data",
        "last_export_path": "prompts.txt",
        "comfyui_url": "127.0.0.1:8188",
        "comfyui_workflow_path": "workflow_api.json",
        "last_project": "",
        "recent_projects": [],
    }


def _normalize_project_path(path):
    return os.path.abspath(os.path.expanduser(path)) if path else ""


def _project_display_name(path):
    project_dir = os.path.basename(os.path.dirname(path))
    return project_dir or os.path.basename(path) or "project.json"


def load_settings():
    defaults = _default_settings()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
                    defaults["recent_projects"] = [
                        item for item in defaults.get("recent_projects", [])
                        if isinstance(item, dict) and item.get("path")
                    ][:MAX_RECENT_PROJECTS]
                    return defaults
        except Exception:
            pass
    return defaults

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)
    except Exception:
        pass


def get_last_project_path(settings):
    return _normalize_project_path(settings.get("last_project", ""))


def get_recent_projects(settings):
    recent_projects = settings.get("recent_projects", [])
    if not isinstance(recent_projects, list):
        return []
    return [
        {
            "name": str(item.get("name") or _project_display_name(item.get("path", ""))),
            "path": _normalize_project_path(item.get("path", "")),
            "last_opened": str(item.get("last_opened", "")),
        }
        for item in recent_projects
        if isinstance(item, dict) and item.get("path")
    ][:MAX_RECENT_PROJECTS]


def remember_project(settings, project_path, project_name=None):
    normalized_path = _normalize_project_path(project_path)
    if not normalized_path:
        return settings

    opened_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    recent = [
        item for item in get_recent_projects(settings)
        if os.path.normcase(item["path"]) != os.path.normcase(normalized_path)
    ]
    recent.insert(0, {
        "name": project_name or _project_display_name(normalized_path),
        "path": normalized_path,
        "last_opened": opened_at,
    })
    settings["last_project"] = normalized_path
    settings["recent_projects"] = recent[:MAX_RECENT_PROJECTS]
    return settings
