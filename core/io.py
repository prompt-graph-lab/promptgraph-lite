import os
import glob
import json
import shutil
from dataclasses import asdict
import dataclasses
from datetime import datetime, timezone
from typing import List, Tuple
from core.project import Project, PromptLine, PromptNode
from core.parser import parse_prompt
from core.graph_builder import build_graph
import logging

logger = logging.getLogger(__name__)

IMAGE_METADATA_EXTENSIONS = {".png"}
PROMPT_METADATA_KEYS = {
    "parameters",
    "prompt",
    "positive",
    "positive_prompt",
    "description",
    "caption",
}
A1111_PARAM_START_KEYS = (
    "Steps",
    "Sampler",
    "Schedule type",
    "CFG scale",
    "Seed",
    "Size",
    "Model hash",
    "Model",
    "Denoising strength",
    "Clip skip",
    "RNG",
    "Hires Module 1",
    "Hires CFG Scale",
    "Hires upscale",
    "Hires steps",
    "Hires upscaler",
    "Lora hashes",
    "Version",
    "Module 1",
)

def _default_project_metadata() -> dict:
    return {
        "image_imports": [],
        "comfyui_workflows": [],
        "generation_jobs": [],
        "candidate_images": [],
    }

def _normalize_project_metadata(metadata) -> dict:
    normalized = _default_project_metadata()
    if isinstance(metadata, dict):
        normalized.update(metadata)
    return normalized

def project_dir_from_path(project_path: str) -> str:
    return os.path.dirname(os.path.abspath(project_path)) if project_path else ""

def ensure_project_folder_layout(project_path: str) -> dict:
    if not project_path:
        return {}

    project_dir = project_dir_from_path(project_path)
    folders = {}
    for folder_name in ("generated",):
        folder_path = os.path.join(project_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        folders[folder_name] = folder_path
    return folders

def _safe_project_name(project_name: str) -> str:
    clean_name = (project_name or "").strip()
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else "_" for ch in clean_name).strip()
    return safe_name or "PromptGraphLiteProject"

def create_project_workspace(parent_dir: str, project_name: str) -> tuple[str | None, dict, str | None]:
    clean_parent_raw = (parent_dir or "").strip()
    if not clean_parent_raw:
        return None, {}, "プロジェクトフォルダを入力してください。"
    if not (project_name or "").strip():
        return None, {}, "プロジェクト名を入力してください。"
    clean_parent = os.path.abspath(os.path.expanduser(clean_parent_raw))

    safe_name = _safe_project_name(project_name)
    project_dir = os.path.join(clean_parent, safe_name)
    project_path = os.path.join(project_dir, "project.json")

    if os.path.exists(project_path):
        return None, {}, "project.jsonが既に存在します。既存プロジェクトを開くか、別のプロジェクト名を指定してください。"

    os.makedirs(project_dir, exist_ok=True)
    folders = ensure_project_folder_layout(project_path)
    return project_path, folders, None

def _candidate_path(candidate):
    if isinstance(candidate, dict):
        return str(candidate.get("path") or "")
    return str(candidate) if candidate else ""

def _normalize_candidate_record(candidate):
    if isinstance(candidate, dict):
        path = _candidate_path(candidate)
        if not path:
            return None
        record = dict(candidate)
        record["path"] = path
        return record

    path = _candidate_path(candidate)
    if not path:
        return None
    return {"path": path}

def _normalize_generated_candidates(candidates) -> List[dict]:
    normalized = []
    seen = set()
    for candidate in candidates or []:
        record = _normalize_candidate_record(candidate)
        if not record:
            continue
        path = record["path"]
        if path not in seen:
            normalized.append(record)
            seen.add(path)
    return normalized

def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")

def _short_metadata_preview(value, limit: int = 240) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."

def _stringify_metadata_value(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)

def _decode_exif_user_comment(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, (bytes, bytearray)):
        return value

    data = bytes(value)
    prefixes = {
        b"ASCII\x00\x00\x00": "ascii",
        b"UNICODE\x00": "utf-16-be",
        b"JIS\x00\x00\x00\x00\x00": "shift_jis",
    }
    for prefix, encoding in prefixes.items():
        if data.startswith(prefix):
            data = data[len(prefix):]
            try:
                return data.decode(encoding, errors="replace").rstrip("\x00")
            except LookupError:
                break
    return data.decode("utf-8", errors="replace").rstrip("\x00")

def _read_exif_metadata(image) -> dict:
    try:
        from PIL import ExifTags
    except Exception:
        return {}

    try:
        exif = image.getexif()
    except Exception:
        return {}
    if not exif:
        return {}

    metadata = {}
    for tag_id, value in exif.items():
        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if tag_name not in {"ImageDescription", "UserComment", "Software"}:
            continue
        if tag_name == "UserComment":
            value = _decode_exif_user_comment(value)
        if isinstance(value, (str, int, float, bool)):
            metadata[tag_name] = value
    return metadata

def _read_image_metadata(file_path: str) -> tuple[int | None, int | None, dict]:
    try:
        from PIL import Image
    except Exception:
        return None, None, {}

    try:
        with Image.open(file_path) as image:
            width, height = image.size
            metadata = {
                str(key): value
                for key, value in getattr(image, "info", {}).items()
                if isinstance(value, (str, int, float, bool))
            }
            metadata.update(_read_exif_metadata(image))
            return width, height, metadata
    except Exception as exc:
        logger.warning(f"Could not read image metadata from {file_path}: {exc}")
        raise

def _find_prompt_preview(metadata: dict) -> str:
    for key, value in metadata.items():
        key_lower = key.lower()
        if key_lower in PROMPT_METADATA_KEYS or "prompt" in key_lower:
            return _short_metadata_preview(value)
    return ""

def _looks_like_workflow_data(value) -> bool:
    if isinstance(value, dict):
        return True
    if not isinstance(value, str):
        return False

    stripped = value.strip()
    if not stripped or stripped[0] not in ("{", "["):
        return False
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, (dict, list))

def _parse_metadata_json(value):
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped[0] not in ("{", "["):
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None

def _has_comfy_workflow_metadata(metadata: dict) -> bool:
    lowered_metadata = {key.lower(): value for key, value in metadata.items()}
    if "workflow" in lowered_metadata:
        return True
    return _looks_like_workflow_data(lowered_metadata.get("prompt"))

def _looks_like_a1111_param_line(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(f"{key}:") for key in A1111_PARAM_START_KEYS)

def _split_a1111_sections(parameters: str) -> tuple[str, str, str]:
    text = parameters.replace("\r\n", "\n").replace("\r", "\n")
    marker = "\nNegative prompt:"
    if marker in text:
        positive, remainder = text.split(marker, 1)
        remainder_lines = remainder.split("\n")
        params_index = next(
            (index for index, line in enumerate(remainder_lines) if _looks_like_a1111_param_line(line)),
            None,
        )
        if params_index is None:
            return positive.strip(), remainder.strip(), ""
        negative = "\n".join(remainder_lines[:params_index]).strip()
        raw_generation_params = "\n".join(remainder_lines[params_index:]).strip()
        return positive.strip(), negative, raw_generation_params

    lines = text.split("\n")
    params_index = next(
        (index for index, line in enumerate(lines) if _looks_like_a1111_param_line(line)),
        None,
    )
    if params_index is None:
        return text.strip(), "", ""
    positive = "\n".join(lines[:params_index]).strip()
    raw_generation_params = "\n".join(lines[params_index:]).strip()
    return positive, "", raw_generation_params

def _split_a1111_param_chunks(raw_generation_params: str) -> list[str]:
    chunks = []
    current = []
    quote_char = ""
    escape_next = False
    for char in raw_generation_params.replace("\n", ", "):
        if escape_next:
            current.append(char)
            escape_next = False
            continue
        if char == "\\" and quote_char:
            current.append(char)
            escape_next = True
            continue
        if char in ("'", '"'):
            if quote_char == char:
                quote_char = ""
            elif not quote_char:
                quote_char = char
            current.append(char)
            continue
        if char == "," and not quote_char:
            chunk = "".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
            continue
        current.append(char)

    chunk = "".join(current).strip()
    if chunk:
        chunks.append(chunk)
    return chunks

def _parse_a1111_generation_params(raw_generation_params: str) -> dict:
    params = {}
    current_key = ""
    for chunk in _split_a1111_param_chunks(raw_generation_params):
        if ":" not in chunk:
            if current_key:
                params[current_key] = f"{params[current_key]}, {chunk}".strip()
            continue
        key, value = chunk.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            if current_key:
                params[current_key] = f"{params[current_key]}, {chunk}".strip()
            continue
        params[key] = value
        current_key = key
    return params

def _parse_a1111_parameters(parameters: str) -> dict:
    if not isinstance(parameters, str) or not parameters.strip():
        return {}
    prompt_text, negative_prompt, raw_generation_params = _split_a1111_sections(parameters)
    return {
        "source_engine": "webui_a1111",
        "raw_parameters": parameters,
        "prompt_text": prompt_text,
        "negative_prompt": negative_prompt,
        "raw_generation_params": raw_generation_params,
        "generation_params": _parse_a1111_generation_params(raw_generation_params),
    }

def _metadata_value_by_key(metadata: dict, *keys: str):
    lowered = {str(key).lower(): value for key, value in metadata.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None

def _node_link_id(value) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    return None

def _extract_comfy_prompt_fields(prompt_json) -> tuple[str, str]:
    if not isinstance(prompt_json, dict):
        return "", ""

    nodes = prompt_json.get("prompt") if isinstance(prompt_json.get("prompt"), dict) else prompt_json
    if not isinstance(nodes, dict):
        return "", ""

    def node_text(node_id: str | None) -> str:
        if not node_id or node_id not in nodes:
            return ""
        node = nodes.get(node_id) or {}
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        text = inputs.get("text", "")
        return text if isinstance(text, str) else ""

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if "KSampler" not in class_type:
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        positive = node_text(_node_link_id(inputs.get("positive")))
        negative = node_text(_node_link_id(inputs.get("negative")))
        if positive or negative:
            return positive.strip(), negative.strip()

    clip_texts = []
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if "CLIPTextEncode" not in class_type:
            continue
        inputs = node.get("inputs", {})
        if isinstance(inputs, dict) and isinstance(inputs.get("text"), str):
            clip_texts.append(inputs["text"].strip())

    if not clip_texts:
        return "", ""
    if len(clip_texts) == 1:
        return clip_texts[0], ""
    return clip_texts[0], clip_texts[1]

def _extract_image_prompt_fields(metadata: dict) -> dict:
    fields = {
        "source_engine": "",
        "metadata_sources": [],
        "raw_parameters": "",
        "prompt_text": "",
        "negative_prompt": "",
        "raw_generation_params": "",
        "generation_params": {},
        "workflow_metadata_keys": [],
    }

    parameters = _metadata_value_by_key(metadata, "parameters")
    if isinstance(parameters, str):
        a1111_fields = _parse_a1111_parameters(parameters)
        if a1111_fields:
            fields.update(a1111_fields)
            fields["metadata_sources"].append("a1111_parameters")

    software = _metadata_value_by_key(metadata, "Software")
    image_description = _metadata_value_by_key(metadata, "ImageDescription")
    user_comment = _metadata_value_by_key(metadata, "UserComment")
    has_exif_generation_metadata = any(
        isinstance(value, str) and value.strip()
        for value in (software, image_description, user_comment)
    )
    if has_exif_generation_metadata:
        fields["metadata_sources"].append("exif")
    if isinstance(software, str) and software.strip().lower() == "novelai":
        fields["source_engine"] = "novelai"
        fields["metadata_sources"].append("novelai_exif")
    if isinstance(image_description, str) and image_description.strip() and not fields["prompt_text"]:
        fields["prompt_text"] = image_description.strip()
        fields["raw_parameters"] = image_description
    if isinstance(user_comment, str) and user_comment.strip():
        fields.setdefault("exif_user_comment", user_comment)

    explicit_positive = _metadata_value_by_key(metadata, "positive_prompt", "positive")
    if isinstance(explicit_positive, str) and explicit_positive.strip():
        fields["prompt_text"] = explicit_positive.strip()

    explicit_negative = _metadata_value_by_key(metadata, "negative_prompt", "negative")
    if isinstance(explicit_negative, str) and explicit_negative.strip():
        fields["negative_prompt"] = explicit_negative.strip()

    prompt_value = _metadata_value_by_key(metadata, "prompt")
    prompt_json = _parse_metadata_json(prompt_value)
    if prompt_json is not None:
        fields["workflow_metadata_keys"].append("prompt")
        fields["metadata_sources"].append("comfy_prompt")
        comfy_positive, comfy_negative = _extract_comfy_prompt_fields(prompt_json)
        if comfy_positive and not fields["prompt_text"]:
            fields["prompt_text"] = comfy_positive
        if comfy_negative and not fields["negative_prompt"]:
            fields["negative_prompt"] = comfy_negative
    elif isinstance(prompt_value, str) and prompt_value.strip() and not fields["prompt_text"]:
        fields["prompt_text"] = prompt_value.strip()

    workflow_value = _metadata_value_by_key(metadata, "workflow")
    if _parse_metadata_json(workflow_value) is not None:
        fields["workflow_metadata_keys"].append("workflow")
        fields["metadata_sources"].append("comfy_workflow")

    if not fields["prompt_text"]:
        for key in ("description", "caption"):
            value = _metadata_value_by_key(metadata, key)
            if isinstance(value, str) and value.strip():
                fields["prompt_text"] = value.strip()
                break

    fields["metadata_sources"] = list(dict.fromkeys(fields["metadata_sources"]))
    return fields

def scan_image_directory_metadata(source_directory: str) -> dict:
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    images = []

    if not os.path.isdir(source_directory):
        return {
            "source_directory": source_directory,
            "imported_at": imported_at,
            "image_count": 0,
            "metadata_count": 0,
            "comfy_workflow_count": 0,
            "images": [],
            "warnings": [f"Directory not found: {source_directory}"],
        }

    for root, _dirs, files in os.walk(source_directory):
        for file_name in sorted(files):
            extension = os.path.splitext(file_name)[1].lower()
            if extension not in IMAGE_METADATA_EXTENSIONS:
                continue

            image_path = os.path.abspath(os.path.join(root, file_name))
            warning = ""
            width = None
            height = None
            metadata = {}
            try:
                stat = os.stat(image_path)
                width, height, metadata = _read_image_metadata(image_path)
            except Exception as exc:
                warning = _short_metadata_preview(exc, limit=160)
                try:
                    stat = os.stat(image_path)
                except OSError:
                    continue

            metadata_keys = sorted(metadata.keys())
            raw_metadata = {
                key: _stringify_metadata_value(metadata[key])
                for key in metadata_keys
            }
            prompt_fields = _extract_image_prompt_fields(metadata)
            has_comfy_workflow = _has_comfy_workflow_metadata(metadata)
            image_info = {
                "path": image_path,
                "filename": file_name,
                "extension": extension,
                "size_bytes": stat.st_size,
                "modified_at": _iso_from_timestamp(stat.st_mtime),
                "width": width,
                "height": height,
                "has_metadata": bool(metadata_keys),
                "metadata_keys": metadata_keys,
                "has_comfy_workflow": has_comfy_workflow,
                "prompt_preview": _find_prompt_preview(metadata),
                "source_engine": prompt_fields["source_engine"],
                "metadata_sources": prompt_fields["metadata_sources"],
                "raw_parameters": prompt_fields["raw_parameters"],
                "prompt_text": prompt_fields["prompt_text"],
                "negative_prompt": prompt_fields["negative_prompt"],
                "raw_generation_params": prompt_fields["raw_generation_params"],
                "generation_params": prompt_fields["generation_params"],
                "workflow_metadata_keys": prompt_fields["workflow_metadata_keys"],
                "raw_metadata": raw_metadata,
            }
            if warning:
                image_info["warning"] = warning
            images.append(image_info)

    metadata_count = sum(1 for image in images if image["has_metadata"])
    comfy_workflow_count = sum(1 for image in images if image["has_comfy_workflow"])
    return {
        "source_directory": os.path.abspath(source_directory),
        "imported_at": imported_at,
        "image_count": len(images),
        "metadata_count": metadata_count,
        "comfy_workflow_count": comfy_workflow_count,
        "images": images,
        "warnings": [image["warning"] for image in images if image.get("warning")],
    }

def add_image_metadata_import(project: Project, source_directory: str) -> dict:
    project.project_metadata = _normalize_project_metadata(getattr(project, "project_metadata", None))
    import_summary = scan_image_directory_metadata(source_directory)
    project.project_metadata.setdefault("image_imports", []).append(import_summary)
    return import_summary

def _latest_image_metadata_import(project: Project) -> dict | None:
    project.project_metadata = _normalize_project_metadata(getattr(project, "project_metadata", None))
    image_imports = project.project_metadata.get("image_imports", [])
    if not image_imports:
        return None
    latest_import = image_imports[-1]
    return latest_import if isinstance(latest_import, dict) else None

def _image_import_prompt_text(image_info: dict) -> str:
    return str(image_info.get("prompt_text") or image_info.get("prompt_preview") or "").strip()

def summarize_image_metadata_line_import(project: Project) -> dict:
    latest_import = _latest_image_metadata_import(project)
    images = latest_import.get("images", []) if latest_import else []
    prompt_count = 0
    skipped_count = 0
    for image_info in images:
        if not isinstance(image_info, dict):
            skipped_count += 1
        elif _image_import_prompt_text(image_info):
            prompt_count += 1
        else:
            skipped_count += 1
    return {
        "has_import": latest_import is not None,
        "line_count": prompt_count,
        "skipped_count": skipped_count,
    }

def _next_image_metadata_line_id(existing_ids: set[str], sequence: int) -> tuple[str, int]:
    while True:
        line_id = f"imgmeta_{sequence:04d}"
        sequence += 1
        if line_id not in existing_ids:
            existing_ids.add(line_id)
            return line_id, sequence

def create_prompt_lines_from_latest_image_import(project: Project) -> tuple[Project, dict]:
    latest_import = _latest_image_metadata_import(project)
    if not latest_import:
        return project, {"created_count": 0, "skipped_count": 0, "has_import": False}

    start_index = max((line.current_index for line in project.prompt_lines), default=-1) + 1
    existing_ids = {line.id for line in project.prompt_lines}
    sequence = 1
    created_count = 0
    skipped_count = 0

    for image_info in latest_import.get("images", []):
        if not isinstance(image_info, dict):
            skipped_count += 1
            continue

        prompt_text = _image_import_prompt_text(image_info)
        if not prompt_text:
            skipped_count += 1
            continue

        line_index = start_index + created_count
        line_id, sequence = _next_image_metadata_line_id(existing_ids, sequence)
        prompt_line = PromptLine(
            id=line_id,
            original_file_name=str(image_info.get("filename") or os.path.basename(image_info.get("path", "")) or "image"),
            original_index=line_index,
            current_index=line_index,
            original_text=prompt_text,
            current_text=prompt_text,
            tokens=parse_prompt(prompt_text),
            image_path=image_info.get("path"),
        )
        prompt_line.negative_prompt = str(image_info.get("negative_prompt") or "").strip()
        project.prompt_lines.append(prompt_line)
        created_count += 1

    project = build_graph(project)
    return project, {
        "created_count": created_count,
        "skipped_count": skipped_count,
        "has_import": True,
    }

def load_directory(dir_path: str, max_depth: int = None) -> Project:
    project = Project(source_directory=dir_path)
    txt_files = sorted(glob.glob(os.path.join(dir_path, "*.txt")))
    
    line_index = 0
    for file_path in txt_files:
        file_name = os.path.basename(file_path)
        base_name = os.path.splitext(file_name)[0]
        
        image_path = None
        for ext in ['.png', '.jpg', '.jpeg', '.PNG', '.JPG', '.JPEG']:
            img_cand = os.path.join(dir_path, base_name + ext)
            if os.path.exists(img_cand):
                image_path = img_cand
                break
                
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for text in lines:
                text = text.strip()
                if not text:
                    continue # 空行スキップ
                
                # 括弧などのSDの特殊構文を破壊しないように単純なパース
                tokens = parse_prompt(text)
                if not tokens:
                    continue
                    
                line_id = f"line_{line_index}"
                
                gen_img_path = None
                candidate_image_paths = []
                output_dir = os.path.join(dir_path, "generated")
                if os.path.exists(output_dir):
                    cands = glob.glob(os.path.join(output_dir, f"gen_{line_id}_*.png"))
                    if cands:
                        cands.sort(key=os.path.getmtime, reverse=True)
                        candidate_image_paths = list(reversed(cands))
                        gen_img_path = cands[0]
                        
                prompt_line = PromptLine(
                    id=line_id,
                    original_file_name=file_name,
                    original_index=line_index,
                    current_index=line_index,
                    original_text=text,
                    current_text=text,
                    tokens=tokens,
                    image_path=image_path,
                    generated_image_path=gen_img_path
                )
                prompt_line.candidate_image_paths = candidate_image_paths
                prompt_line.generated_candidates = _normalize_generated_candidates(candidate_image_paths)
                project.prompt_lines.append(prompt_line)
                line_index += 1
        except Exception as e:
            logger.error(f"Error reading {file_name}: {e}")
            
    return build_graph(project, max_depth=max_depth)

def export_to_txt(project: Project, output_path: str, include_comments: bool = False, disabled_modules: set = None):
    if disabled_modules is None:
        disabled_modules = set()
        
    from core.operations import get_active_tokens
    
    valid_lines = [l for l in project.prompt_lines if not l.deleted]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        current_file = ""
        for line in valid_lines:
            if include_comments and line.original_file_name != current_file:
                if current_file:
                    f.write("\n")
                f.write(f"# {line.original_file_name}\n")
                current_file = line.original_file_name
                
            active = get_active_tokens(line, disabled_modules)
            f.write(f"{', '.join(active)}\n")

# Prompt/image set export helpers
def _safe_export_stem(file_name: str) -> str:
    stem = os.path.splitext(os.path.basename(file_name or "illustration"))[0]
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem).strip("_")
    return safe_stem or "illustration"

def _unique_export_dir(output_dir: str) -> str:
    output_dir = os.path.abspath(os.path.expanduser(output_dir))
    if not os.path.exists(output_dir) or not os.listdir(output_dir):
        return output_dir

    suffix = 1
    while True:
        candidate = f"{output_dir}_{suffix}"
        if not os.path.exists(candidate):
            return candidate
        suffix += 1

def _resolve_export_image_path(project: Project, image_path: str) -> str:
    if not image_path:
        return ""
    if os.path.exists(image_path):
        return os.path.abspath(image_path)
    if os.path.isabs(image_path):
        return image_path
    source_directory = getattr(project, "source_directory", "") or ""
    if source_directory:
        return os.path.abspath(os.path.join(source_directory, image_path))
    return image_path

def _selected_export_image(project: Project, line: PromptLine) -> tuple[str, str]:
    choices = (
        ("candidate", getattr(line, "selected_candidate_path", None)),
        ("after", getattr(line, "generated_image_path", None)),
        ("reference", getattr(line, "image_path", None)),
    )
    for image_kind, image_path in choices:
        resolved_path = _resolve_export_image_path(project, image_path)
        if resolved_path and os.path.exists(resolved_path):
            return image_kind, resolved_path
    return "", ""

def export_prompt_image_set(project: Project, output_dir: str, disabled_modules: set = None) -> dict:
    if disabled_modules is None:
        disabled_modules = set()

    from core.operations import get_active_tokens

    export_dir = _unique_export_dir(output_dir)
    os.makedirs(export_dir, exist_ok=True)
    prompts_path = os.path.join(export_dir, "prompts.txt")

    copied_images = []
    missing_images = []
    valid_lines = [line for line in project.prompt_lines if not line.deleted]

    with open(prompts_path, "w", encoding="utf-8") as prompt_file:
        for index, line in enumerate(valid_lines, start=1):
            active = get_active_tokens(line, disabled_modules)
            prompt_file.write(f"{', '.join(active)}\n")

            image_kind, image_path = _selected_export_image(project, line)
            if not image_path:
                missing_images.append(getattr(line, "id", f"line_{index}"))
                continue

            extension = os.path.splitext(image_path)[1] or ".png"
            file_stem = _safe_export_stem(getattr(line, "original_file_name", "") or getattr(line, "id", "illustration"))
            output_image_path = os.path.join(export_dir, f"{index:04d}_{image_kind}_{file_stem}{extension}")
            shutil.copy2(image_path, output_image_path)
            copied_images.append(output_image_path)

    return {
        "output_dir": export_dir,
        "prompts_path": prompts_path,
        "prompt_count": len(valid_lines),
        "image_count": len(copied_images),
        "missing_image_count": len(missing_images),
        "copied_images": copied_images,
        "missing_line_ids": missing_images,
        "used_fallback_directory": os.path.abspath(os.path.expanduser(output_dir)) != export_dir,
    }

# JSONのエンコード/デコードでSetなどを処理するカスタムEncoder
class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)

def save_project_to_json(project: Project, output_path: str):
    data = asdict(project)
    project_metadata = getattr(project, "project_metadata", None)
    if isinstance(project_metadata, dict):
        data["project_metadata"] = _normalize_project_metadata(project_metadata)
    for line_data, line in zip(data.get("prompt_lines", []), project.prompt_lines):
        candidates = _normalize_generated_candidates(
            getattr(line, "generated_candidates", None) or getattr(line, "candidate_image_paths", [])
        )
        if candidates:
            line_data["generated_candidates"] = candidates
            line_data["candidate_image_paths"] = [candidate["path"] for candidate in candidates]
        selected_candidate_path = getattr(line, "selected_candidate_path", None)
        if selected_candidate_path:
            line_data["selected_candidate_path"] = selected_candidate_path
        continued_from = getattr(line, "continued_from", None)
        if continued_from:
            line_data["continued_from"] = continued_from
        negative_prompt = getattr(line, "negative_prompt", "")
        if negative_prompt:
            line_data["negative_prompt"] = negative_prompt
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, cls=SetEncoder, indent=2, ensure_ascii=False)

def load_project_from_json(json_path: str) -> Project:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # dict から dataclass への復元
    project = Project(source_directory=data.get("source_directory", ""))
    project.project_metadata = _normalize_project_metadata(data.get("project_metadata"))
    
    valid_pl_keys = {f.name for f in dataclasses.fields(PromptLine)}
    for l_data in data.get("prompt_lines", []):
        filtered_data = {k: v for k, v in l_data.items() if k in valid_pl_keys}
        pl = PromptLine(**filtered_data)
        candidates = _normalize_generated_candidates(
            l_data.get("generated_candidates") or l_data.get("candidate_image_paths", [])
        )
        pl.generated_candidates = candidates
        pl.candidate_image_paths = [candidate["path"] for candidate in candidates]
        pl.selected_candidate_path = l_data.get("selected_candidate_path") or getattr(pl, "generated_image_path", None)
        pl.continued_from = l_data.get("continued_from")
        pl.negative_prompt = l_data.get("negative_prompt", "")
        project.prompt_lines.append(pl)
        
    valid_pn_keys = {f.name for f in dataclasses.fields(PromptNode)}
    for n_id, n_data in data.get("nodes", {}).items():
        # jsonから復元するとsetがlistになっているのでsetに戻す
        n_data["prompt_line_ids"] = set(n_data.get("prompt_line_ids", []))
        n_data["prev_node_ids"] = set(n_data.get("prev_node_ids", []))
        n_data["next_node_ids"] = set(n_data.get("next_node_ids", []))
        filtered_data = {k: v for k, v in n_data.items() if k in valid_pn_keys}
        pn = PromptNode(**filtered_data)
        project.nodes[n_id] = pn
        
    project.edges = [tuple(e) for e in data.get("edges", [])]
    
    # line_map の再構築
    project.line_map = {l.id: l for l in project.prompt_lines}
    
    return project
