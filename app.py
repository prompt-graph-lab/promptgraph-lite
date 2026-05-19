import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config
from core.io import load_directory, export_to_txt, export_prompt_image_set, save_project_to_json, load_project_from_json, add_image_metadata_import, create_prompt_lines_from_latest_image_import, create_project_workspace, ensure_project_folder_layout, project_dir_from_path
from core.graph_builder import build_graph
from core.operations import rename_node, delete_nodes, insert_node, duplicate_nodes, move_nodes, merge_duplicates_in_line, merge_duplicates_all_lines, apply_node_weight, insert_subgraph, replace_with_subgraph, rename_word_global, delete_word_global, insert_word_global, count_matches, get_available_modules, get_active_tokens, get_display_tokens, get_display_tokens_from_text, extract_module_structure_from_text
from core.parser import parse_prompt
from core.project import Project
import streamlit.components.v1 as components
import os
import uuid
import copy
import json
from core.comfyui import generate_image_with_progress
from core.settings import load_settings, save_settings, get_last_project_path, get_recent_projects, remember_project, EDITION
import sys
from wordcloud import WordCloud
import matplotlib.pyplot as plt

# --- State Management ---
def normalize_agraph_selection(return_value, project):
    if not return_value:
        return []

    raw_items = return_value if isinstance(return_value, list) else [return_value]
    ids = []

    for item in raw_items:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            if "id" in item:
                ids.append(item["id"])
            elif "node" in item:
                ids.append(item["node"])
        else:
            if hasattr(item, "id"):
                ids.append(item.id)

    valid_ids = []
    for nid in ids:
        if nid in project.nodes and nid not in valid_ids:
            valid_ids.append(nid)

    return valid_ids

if "settings" not in st.session_state:
    st.session_state.settings = load_settings()
if "history" not in st.session_state:
    st.session_state.history = []
if "project" not in st.session_state:
    st.session_state.project = None
if "current_project_path" not in st.session_state:
    st.session_state.current_project_path = ""
if "selected_node_ids" not in st.session_state:
    st.session_state.selected_node_ids = []
if "disabled_modules" not in st.session_state:
    st.session_state.disabled_modules = set()
if "connect_mode" not in st.session_state:
    st.session_state.connect_mode = False
if "connect_nodes" not in st.session_state:
    st.session_state.connect_nodes = []
if "edition" not in st.session_state:
    st.session_state.edition = EDITION
if "show_tutorial" not in st.session_state:
    st.session_state.show_tutorial = True
if "shortcut_feedback" not in st.session_state:
    st.session_state.shortcut_feedback = ""
if "branch_feedback" not in st.session_state:
    st.session_state.branch_feedback = ""

def push_history():
    if st.session_state.project:
        st.session_state.history.append(st.session_state.project.clone())
        # 履歴が多すぎると重くなるので制限
        if len(st.session_state.history) > 20:
            st.session_state.history.pop(0)

def undo():
    if len(st.session_state.history) > 0:
        st.session_state.project = st.session_state.history.pop()
        st.session_state.selected_node_ids = []
        sync_text_areas()

def sync_text_areas():
    if st.session_state.project:
        for line in st.session_state.project.prompt_lines:
            key = f"text_{line.id}"
            if key in st.session_state:
                st.session_state[key] = line.current_text
            
            focus_key = f"focus_text_{line.id}"
            if focus_key in st.session_state:
                st.session_state[focus_key] = line.current_text

def start_new_project():
    st.session_state.history = []
    st.session_state.project = build_graph(Project(source_directory=""))
    st.session_state.current_project_path = ""
    st.session_state.focused_line_id = None
    st.session_state.selected_node_ids = []
    st.session_state.disabled_modules = set()
    st.session_state.connect_mode = False
    st.session_state.connect_nodes = []
    st.session_state.shortcut_feedback = ""
    st.session_state.branch_feedback = ""

def create_new_project_workspace(parent_dir: str, project_name: str) -> tuple[bool, str]:
    project_path, folders, error = create_project_workspace(parent_dir, project_name)
    if error:
        return False, error

    project_root = project_dir_from_path(project_path)
    project = build_graph(Project(source_directory=project_root))
    save_project_to_json(project, project_path)
    st.session_state.history = []
    st.session_state.project = project
    st.session_state.current_project_path = os.path.abspath(project_path)
    st.session_state.focused_line_id = None
    st.session_state.selected_node_ids = []
    st.session_state.disabled_modules = set()
    st.session_state.connect_mode = False
    st.session_state.connect_nodes = []
    st.session_state.shortcut_feedback = ""
    st.session_state.branch_feedback = ""
    st.session_state.settings = remember_project(
        st.session_state.settings,
        st.session_state.current_project_path,
    )
    save_settings(st.session_state.settings)
    sync_text_areas()
    generated_dir = folders.get("generated") or os.path.join(project_root, "generated")
    return True, f"project.jsonを作成しました。generatedフォルダを作成しました: {generated_dir}"

def get_generated_output_dir(project) -> str:
    source_directory = getattr(project, "source_directory", "") if project else ""
    if source_directory:
        return os.path.join(source_directory, "generated")
    current_project_path = st.session_state.get("current_project_path") or ""
    if current_project_path:
        return os.path.join(project_dir_from_path(current_project_path), "generated")
    return os.path.join(".", "generated")

def load_project_json_into_session(project_path: str) -> bool:
    if not os.path.exists(project_path):
        st.warning(f"プロジェクトファイルが見つかりません: {project_path}")
        return False

    st.session_state.history = []
    project = load_project_from_json(project_path)
    project = build_graph(project)
    st.session_state.project = project
    st.session_state.current_project_path = os.path.abspath(project_path)
    ensure_project_folder_layout(st.session_state.current_project_path)
    st.session_state.focused_line_id = None
    st.session_state.selected_node_ids = []
    st.session_state.connect_mode = False
    st.session_state.connect_nodes = []
    sync_text_areas()

    st.session_state.settings = remember_project(
        st.session_state.settings,
        st.session_state.current_project_path,
    )
    save_settings(st.session_state.settings)
    return True

def get_line_by_id(project, line_id):
    if not project or not line_id:
        return None
    return next(
        (line for line in project.prompt_lines if line.id == line_id and not getattr(line, "deleted", False)),
        None,
    )

def _shortcut_context():
    line = get_line_by_id(st.session_state.get("project"), st.session_state.get("focused_line_id"))
    return {
        "has_focus": bool(line),
        "focused_prompt": line.current_text if line else "",
        "can_undo": len(st.session_state.history) > 0,
    }

def inject_keyboard_shortcuts():
    shortcut_context = _shortcut_context()
    components.html(
        f"""
        <script>
        (() => {{
            const doc = window.parent.document;
            const labels = {{
                clear: "Shortcut Action: Clear Selection",
                undo: "Shortcut Action: Undo",
                save: "Shortcut Action: Save Focused Line",
                copySuccess: "Shortcut Action: Copy Success",
                copyFailed: "Shortcut Action: Copy Failed",
                focusEditor: "Shortcut Action: Focus Editor",
            }};

            window.__promptGraphShortcutState = {{
                hasFocus: {json.dumps(shortcut_context["has_focus"])},
                focusedPrompt: {json.dumps(shortcut_context["focused_prompt"])},
                canUndo: {json.dumps(shortcut_context["can_undo"])},
            }};

            function findButton(label) {{
                return Array.from(doc.querySelectorAll("button")).find(
                    (button) => ((button.textContent || "").trim()).includes(label)
                );
            }}

            function hideShortcutButtons() {{
                Object.values(labels).forEach((label) => {{
                    const button = findButton(label);
                    if (!button) return;
                    const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
                    if (wrapper) wrapper.style.display = "none";
                }});
            }}

            const existingScript = doc.getElementById("promptgraph-shortcuts-v1");
            if (existingScript) existingScript.remove();

            const scriptTag = doc.createElement("script");
            scriptTag.id = "promptgraph-shortcuts-v1";
            scriptTag.innerHTML = `
                    if (window.__promptGraphShortcutHandler) {{
                        document.removeEventListener("keydown", window.__promptGraphShortcutHandler, true);
                    }}
                    window.__promptGraphShortcutHandler = async function(e) {{
                        const state = window.__promptGraphShortcutState || {{}};
                        const isModifier = e.ctrlKey || e.metaKey;
                        const key = (e.key || "").toLowerCase();
                        const code = e.code || "";
                        const tag = e.target ? e.target.tagName : "";
                        const editable = tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable);
                        const labels = {{
                            clear: "Shortcut Action: Clear Selection",
                            undo: "Shortcut Action: Undo",
                            save: "Shortcut Action: Save Focused Line",
                            copySuccess: "Shortcut Action: Copy Success",
                            copyFailed: "Shortcut Action: Copy Failed",
                            focusEditor: "Shortcut Action: Focus Editor",
                        }};
                        const findButton = (label) => Array.from(document.querySelectorAll("button")).find(
                            (button) => ((button.textContent || "").trim()).includes(label)
                        );
                        const clickShortcut = (label) => {{
                            const button = findButton(label);
                            if (button) button.click();
                            return Boolean(button);
                        }};
                        const focusEditTextArea = () => {{
                            const textAreas = Array.from(document.querySelectorAll("textarea"));
                            const textArea = textAreas[textAreas.length - 1];
                            if (!textArea) return false;
                            textArea.scrollIntoView({{ behavior: "smooth", block: "center" }});
                            textArea.focus();
                            return true;
                        }};
                        const handled = () => {{
                            e.preventDefault();
                            e.stopPropagation();
                            if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                        }};

                        if (e.key === "Escape") {{
                            if (clickShortcut(labels.clear)) handled();
                            return;
                        }}
                        if (isModifier && (key === "z" || code === "KeyZ")) {{
                            if (editable || !state.canUndo) return;
                            if (clickShortcut(labels.undo)) handled();
                            return;
                        }}
                        if (isModifier && (key === "s" || code === "KeyS")) {{
                            if (!state.hasFocus) return;
                            handled();
                            clickShortcut(labels.save);
                            return;
                        }}
                        if ((e.key === "F2" || e.key === "Enter") && state.hasFocus && !editable && !isModifier) {{
                            if (focusEditTextArea()) {{
                                clickShortcut(labels.focusEditor);
                                handled();
                            }}
                            return;
                        }}
                        if (isModifier && (key === "c" || code === "KeyC") && state.hasFocus && !editable) {{
                            handled();
                            if (!navigator.clipboard) {{
                                clickShortcut(labels.copyFailed);
                                return;
                            }}
                            try {{
                                await navigator.clipboard.writeText(state.focusedPrompt || "");
                                clickShortcut(labels.copySuccess);
                            }} catch (err) {{
                                clickShortcut(labels.copyFailed);
                            }}
                        }}
                    }};
                    document.addEventListener("keydown", window.__promptGraphShortcutHandler, true);
                `;
            doc.head.appendChild(scriptTag);

            hideShortcutButtons();
            setTimeout(hideShortcutButtons, 250);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )

def render_shortcut_actions():
    clear_selection = st.sidebar.button("Shortcut Action: Clear Selection", key="shortcut_clear_selection")
    shortcut_undo = st.sidebar.button("Shortcut Action: Undo", key="shortcut_undo")
    save_focused_line = st.sidebar.button("Shortcut Action: Save Focused Line", key="shortcut_save_focused_line")
    copy_success = st.sidebar.button("Shortcut Action: Copy Success", key="shortcut_copy_success")
    copy_failed = st.sidebar.button("Shortcut Action: Copy Failed", key="shortcut_copy_failed")
    focus_editor = st.sidebar.button("Shortcut Action: Focus Editor", key="shortcut_focus_editor")

    if clear_selection:
        st.session_state.selected_node_ids = []
        st.session_state.connect_mode = False
        st.session_state.connect_nodes = []
        if "selected_lines" in st.session_state:
            st.session_state.selected_lines = {}
        st.session_state.shortcut_feedback = "選択を解除しました"
        st.rerun()

    if shortcut_undo and st.session_state.history:
        prev_focus = st.session_state.get("focused_line_id")
        undo()
        restore_focus_after_graph_update(prev_focus)
        st.session_state.shortcut_feedback = "元に戻しました"
        st.rerun()

    if save_focused_line:
        line = get_line_by_id(st.session_state.get("project"), st.session_state.get("focused_line_id"))
        if line:
            new_text = st.session_state.get(f"focus_text_{line.id}", line.current_text)
            if new_text != line.current_text:
                if st.session_state.edition == "FREE":
                    old_structure = extract_module_structure_from_text(line.current_text)
                    new_structure = extract_module_structure_from_text(new_text)
                    if old_structure != new_structure:
                        st.session_state.shortcut_feedback = "保存できません"
                        st.error("Lite版ではModuleタグを変更できません。")
                        st.stop()
                update_line_text(line.id, new_text)
                st.session_state.shortcut_feedback = "フォーカス中の生成ソースを保存しました"
                st.rerun()
            else:
                st.session_state.shortcut_feedback = "保存する変更はありません"
                st.rerun()
        else:
            st.session_state.shortcut_feedback = "フォーカス中のイラストがありません"
            st.rerun()

    if copy_success:
        st.session_state.shortcut_feedback = "フォーカス中の生成ソースをコピーしました"
        st.rerun()

    if copy_failed:
        st.session_state.shortcut_feedback = "コピーに失敗しました"
        st.rerun()

    if focus_editor:
        st.session_state.shortcut_feedback = "編集欄にフォーカスしました"
        st.rerun()

def update_line_text(line_id: str, new_text: str):
    push_history()
    for line in st.session_state.project.prompt_lines:
        if line.id == line_id:
            line.current_text = new_text
            line.tokens = parse_prompt(new_text)
            line.edited = True
            break
    # グラフ再構築
    prev_focus = st.session_state.get("focused_line_id")
    st.session_state.project = build_graph(st.session_state.project)
    restore_focus_after_graph_update(prev_focus)

def delete_line(line_id: str):
    push_history()
    for line in st.session_state.project.prompt_lines:
        if line.id == line_id:
            line.deleted = True
            break
    prev_focus = st.session_state.get("focused_line_id")
    st.session_state.project = build_graph(st.session_state.project)
    restore_focus_after_graph_update(prev_focus)
    # Check if selected nodes still exist
    st.session_state.selected_node_ids = [nid for nid in st.session_state.selected_node_ids if nid in st.session_state.project.nodes]

def duplicate_line(line_id: str, focus_new_branch: bool = False) -> str | None:
    push_history()
    new_lines = []
    new_line_id = None
    for line in st.session_state.project.prompt_lines:
        new_lines.append(line)
        if line.id == line_id:
            new_line = copy.deepcopy(line)
            new_line.id = f"line_{uuid.uuid4().hex[:8]}"
            new_line.duplicated_from = line.id
            new_line.edited = True
            new_line_id = new_line.id
            new_lines.append(new_line)

    if not new_line_id:
        return None

    st.session_state.project.prompt_lines = new_lines
    # indexの振り直し
    for i, l in enumerate(st.session_state.project.prompt_lines):
        l.current_index = i

    prev_focus = new_line_id if focus_new_branch else st.session_state.get("focused_line_id")
    st.session_state.project = build_graph(st.session_state.project)
    restore_focus_after_graph_update(prev_focus)
    st.session_state.selected_node_ids = [nid for nid in st.session_state.selected_node_ids if nid in st.session_state.project.nodes]
    sync_text_areas()
    return new_line_id

def continue_story_from_line(line_id: str) -> str | None:
    source_line = next((line for line in st.session_state.project.prompt_lines if line.id == line_id), None)
    if not source_line:
        return None

    push_history()
    new_lines = []
    new_line_id = None
    continuation_reference = getattr(source_line, "generated_image_path", None) or getattr(source_line, "image_path", None)

    for line in st.session_state.project.prompt_lines:
        new_lines.append(line)
        if line.id == line_id:
            new_line = copy.deepcopy(line)
            new_line.id = f"line_{uuid.uuid4().hex[:8]}"
            new_line.duplicated_from = line.id
            new_line.continued_from = line.id
            new_line.edited = True
            new_line.image_path = continuation_reference
            new_line.generated_image_path = None
            new_line.generated_candidates = []
            new_line.candidate_image_paths = []
            new_line.selected_candidate_path = None
            new_line_id = new_line.id
            new_lines.append(new_line)

    if not new_line_id:
        return None

    st.session_state.project.prompt_lines = new_lines
    for i, l in enumerate(st.session_state.project.prompt_lines):
        l.current_index = i

    st.session_state.project = build_graph(st.session_state.project)
    restore_focus_after_graph_update(new_line_id)
    st.session_state.selected_node_ids = [nid for nid in st.session_state.selected_node_ids if nid in st.session_state.project.nodes]
    sync_text_areas()
    return new_line_id

def get_candidate_image_paths(line) -> list[str]:
    return [_candidate_path(candidate) for candidate in _get_line_generated_candidates(line)]

def count_line_candidates(line) -> int:
    candidate_paths = []
    candidates = getattr(line, "generated_candidates", None)
    legacy_paths = getattr(line, "candidate_image_paths", None)
    if isinstance(candidates, list):
        candidate_paths.extend(_candidate_path(candidate) for candidate in candidates)
    if isinstance(legacy_paths, list):
        candidate_paths.extend(_candidate_path(candidate) for candidate in legacy_paths)
    return len({path for path in candidate_paths if path})

def project_stats(project) -> dict:
    if not project:
        return {
            "source_directory": "",
            "active_lines": 0,
            "branch_lines": 0,
            "continued_lines": 0,
            "candidate_images": 0,
            "after_images": 0,
        }

    active_lines = [
        line for line in getattr(project, "prompt_lines", [])
        if not getattr(line, "deleted", False)
    ]
    continued_lines = [
        line for line in active_lines
        if getattr(line, "continued_from", None)
    ]
    branch_lines = [
        line for line in active_lines
        if getattr(line, "duplicated_from", None) and not getattr(line, "continued_from", None)
    ]
    return {
        "source_directory": getattr(project, "source_directory", "") or "",
        "active_lines": len(active_lines),
        "branch_lines": len(branch_lines),
        "continued_lines": len(continued_lines),
        "candidate_images": sum(count_line_candidates(line) for line in active_lines),
        "after_images": sum(1 for line in active_lines if getattr(line, "generated_image_path", None)),
    }

REGULAR_COMFY_WORKFLOW_ERROR = (
    "通常形式のComfyUI workflow JSONのようです。Enable Dev Mode Options → Save (API Format)で出力した"
    "API形式のworkflow_api.jsonを使用してください。"
)

def _load_json_from_text(value: str):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None

def _is_executable_comfy_workflow(value) -> bool:
    if not isinstance(value, dict):
        return False
    nodes = value.get("nodes", value)
    if not isinstance(nodes, dict):
        return False
    return any(
        isinstance(node, dict) and isinstance(node.get("inputs"), dict)
        for node in nodes.values()
    )

def _is_regular_comfy_ui_workflow(value) -> bool:
    if not isinstance(value, dict):
        return False
    return isinstance(value.get("nodes"), list) and (
        "last_node_id" in value or "last_link_id" in value or "links" in value
    )

def _validate_api_comfy_workflow(workflow_json):
    if _is_regular_comfy_ui_workflow(workflow_json):
        raise ValueError(REGULAR_COMFY_WORKFLOW_ERROR)
    if not _is_executable_comfy_workflow(workflow_json):
        raise ValueError("workflow JSONがComfyUI API形式ではないか、ノード入力がありません。")

def _replace_clip_text_prompts(workflow_json, line):
    if not isinstance(workflow_json, dict):
        return 0

    nodes = workflow_json.get("nodes", workflow_json)
    if not isinstance(nodes, dict):
        return 0

    replacements = 0
    clip_inputs = []
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        if "CLIPTextEncode" not in str(node.get("class_type", "")):
            continue
        inputs = node.get("inputs", {})
        if isinstance(inputs, dict) and isinstance(inputs.get("text"), str):
            clip_inputs.append(inputs)

    for inputs in clip_inputs:
        if inputs.get("text"):
            inputs["text"] = getattr(line, "current_text", "") or ""
            replacements += 1

    return replacements

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

def _normalize_candidate_records(candidates):
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

def _make_generated_candidate_record(path, line, source):
    if not path:
        return None
    return {
        "path": str(path),
        "prompt_text": getattr(line, "current_text", "") or "",
        "source": source,
        "origin_line_id": getattr(line, "id", "") or "",
        "origin_line_index": getattr(line, "current_index", None),
    }

def _get_line_generated_candidates(line):
    candidates = getattr(line, "generated_candidates", None)
    legacy_paths = getattr(line, "candidate_image_paths", None)
    if not isinstance(candidates, list):
        candidates = []
    if isinstance(legacy_paths, list):
        candidates = [*candidates, *legacy_paths]
    line.generated_candidates = _normalize_candidate_records(candidates)
    line.candidate_image_paths = [_candidate_path(candidate) for candidate in line.generated_candidates]
    return line.generated_candidates

def _append_line_generated_candidates(line, candidates_to_add):
    if isinstance(candidates_to_add, (str, dict)):
        candidates_to_add = [candidates_to_add]
    candidates = _get_line_generated_candidates(line)
    seen = {_candidate_path(candidate) for candidate in candidates}
    for candidate in candidates_to_add or []:
        record = _normalize_candidate_record(candidate)
        if not record:
            continue
        path = record["path"]
        if path not in seen:
            candidates.append(record)
            seen.add(path)
    line.generated_candidates = candidates
    line.candidate_image_paths = [_candidate_path(candidate) for candidate in candidates]

def add_candidate_image(line, image_path: str):
    _append_line_generated_candidates(line, _make_generated_candidate_record(image_path, line, "single_generate"))

def set_candidate_as_after(line, image_path: str):
    push_history()
    add_candidate_image(line, image_path)
    line.generated_image_path = image_path
    line.selected_candidate_path = image_path

def set_candidate_as_reference(line, image_path: str):
    push_history()
    add_candidate_image(line, image_path)
    line.image_path = image_path

def build_lite_generation_workflow(target_line):
    if not os.path.exists(st.session_state.comfy_workflow_path):
        raise FileNotFoundError(f"workflow JSONが見つかりません: {st.session_state.comfy_workflow_path}")

    with open(st.session_state.comfy_workflow_path, 'r', encoding='utf-8') as f:
        wf_str = f.read()

    mapping = st.session_state.settings.get("comfy_mapping")
    fallback_prompt = st.session_state.settings.get("fallback_prompt", "(masterpiece:1.0)")
    active_tokens = get_active_tokens(target_line, st.session_state.disabled_modules, fallback_prompt=fallback_prompt)
    injection_line = copy.deepcopy(target_line)
    injection_line.current_text = ", ".join(active_tokens)

    if isinstance(mapping, dict) and "group_map" in mapping:
        workflow_json = json.loads(wf_str)
        _validate_api_comfy_workflow(workflow_json)
        from core.comfyui import build_prompt_by_group, inject_prompt_to_workflow
        grouped = build_prompt_by_group(st.session_state.project, target_line, st.session_state.disabled_modules)
        return inject_prompt_to_workflow(workflow_json, grouped, mapping, fallback_prompt=fallback_prompt)

    if "__PROMPT__" not in wf_str:
        workflow_json = json.loads(wf_str)
        _validate_api_comfy_workflow(workflow_json)
        if _replace_clip_text_prompts(workflow_json, injection_line) == 0:
            st.warning("workflow JSONに'__PROMPT__'がありません。プロンプトが反映されない可能性があります。")
        return workflow_json

    escaped_prompt = json.dumps(", ".join(active_tokens))[1:-1]
    workflow_json = json.loads(wf_str.replace("__PROMPT__", escaped_prompt))
    _validate_api_comfy_workflow(workflow_json)
    return workflow_json

def render_lite_comfy_workflow_debug_preview(target_line):
    with st.expander("Debug: ComfyUI workflowプレビュー", expanded=False):
        st.caption("共有workflow JSONパス")
        st.code(st.session_state.comfy_workflow_path or "(not set)", language="text")
        if not os.path.exists(st.session_state.comfy_workflow_path):
            st.warning(f"workflow JSONが見つかりません: {st.session_state.comfy_workflow_path}")
            return
        try:
            workflow_json = build_lite_generation_workflow(target_line)
            st.caption("プロンプト反映後のAPI形式workflow JSON")
            st.code(json.dumps(workflow_json, indent=2, ensure_ascii=False), language="json")
        except Exception as exc:
            st.warning(f"workflowプレビューを作成できませんでした: {exc}")

def move_line(line_id: str, visible_line_ids: list[str], direction: str) -> bool:
    if line_id not in visible_line_ids:
        return False

    visible_index = visible_line_ids.index(line_id)
    if direction == "up":
        if visible_index == 0:
            return False
        adjacent_line_id = visible_line_ids[visible_index - 1]
    elif direction == "down":
        if visible_index == len(visible_line_ids) - 1:
            return False
        adjacent_line_id = visible_line_ids[visible_index + 1]
    else:
        return False

    line_indices = {line.id: i for i, line in enumerate(st.session_state.project.prompt_lines)}
    if line_id not in line_indices or adjacent_line_id not in line_indices:
        return False

    push_history()
    target_index = line_indices[line_id]
    adjacent_index = line_indices[adjacent_line_id]
    prompt_lines = st.session_state.project.prompt_lines
    prompt_lines[target_index], prompt_lines[adjacent_index] = prompt_lines[adjacent_index], prompt_lines[target_index]

    for i, line in enumerate(prompt_lines):
        line.current_index = i

    prev_focus = st.session_state.get("focused_line_id")
    st.session_state.project = build_graph(st.session_state.project)
    restore_focus_after_graph_update(prev_focus)
    st.session_state.selected_node_ids = [nid for nid in st.session_state.selected_node_ids if nid in st.session_state.project.nodes]
    sync_text_areas()
    return True

@st.dialog("Pro版について")
def show_upgrade_dialog(message: str):
    st.warning(message)
    st.markdown("""
    ### 🚀 PromptGraph Proでできること

    Pro版は、グラフ構造を使ってイラスト集をより高度かつ効率的に編集・再利用するための上位版です。

    **Pro版機能:**
    - **グラフ構造編集**: イラスト集全体の生成ソースを構造として確認・編集できます。
    - **効率的な再利用**: 既存の構成や表現を整理し、別ルートや派生に活用できます。
    - **Module作成**: 再利用できるプロンプトModuleを作成・保存できます。
    - **ワークフロー同期**: ComfyUI生成をIDEから直接実行できます。

    [FANBOXで支援・Pro版を確認](https://example.com/fanbox)
    """)
    if st.button("閉じる"):
        st.rerun()

def get_structural_stats(old_text, new_text):
    from core.parser import parse_prompt, extract_node_metadata
    from core.operations import get_display_tokens_from_text
    
    old_display_tokens = get_display_tokens_from_text(old_text)
    new_display_tokens = get_display_tokens_from_text(new_text)
    
    # We still want to count modules from the raw tokens
    raw_new_tokens = parse_prompt(new_text)
    
    token_delta = len(new_display_tokens) - len(old_display_tokens)
    mod_count = sum(1 for t in raw_new_tokens if t.startswith("<mod:"))
    has_weights = any(extract_node_metadata(t)["weight"] != 1.0 for t in new_display_tokens)
    
    change_ratio = 0
    if old_display_tokens:
        import difflib
        sm = difflib.SequenceMatcher(None, old_display_tokens, new_display_tokens)
        change_ratio = 1.0 - sm.ratio()
        
    return {
        "token_delta": token_delta,
        "mod_count": mod_count,
        "has_weights": has_weights,
        "change_ratio": change_ratio
    }

def is_free():
    return st.session_state.get("edition") == "FREE"

def require_pro(message: str) -> bool:
    if is_free():
        show_upgrade_dialog(message)
        return False
    return True

def get_free_target_lines_or_block(message: str = "Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。"):
    if is_free():
        focused = st.session_state.get("focused_line_id")
        if not focused:
            st.error(message)
            return None
        return [focused]
    return None

def validate_node_input(text: str) -> bool:
    if not text.strip() or "," in text or "\n" in text:
        st.warning("🚫 入力された文字列に空文字、空白のみ、カンマ、または改行が含まれています。これらは使用できません。")
        return False
    return True

def restore_focus_after_graph_update(previous_focused_line_id):
    if not previous_focused_line_id:
        return

    project = st.session_state.get("project")
    if not project:
        st.session_state.focused_line_id = None
        return

    exists = any(
        line.id == previous_focused_line_id and not getattr(line, "deleted", False)
        for line in project.prompt_lines
    )

    if exists:
        st.session_state.focused_line_id = previous_focused_line_id
    else:
        st.session_state.focused_line_id = None

    if getattr(project, "nodes", None):
        st.session_state.selected_node_ids = [
            nid for nid in st.session_state.selected_node_ids
            if nid in project.nodes
        ]

def get_neighborhood_node_ids(project, selected_node_ids, steps):
    if not project or not selected_node_ids or steps is None:
        return None

    valid_selected = [
        nid for nid in selected_node_ids
        if nid in getattr(project, "nodes", {})
    ]

    if not valid_selected:
        return set()

    forward = {}
    backward = {}

    for source, target in getattr(project, "edges", []):
        forward.setdefault(source, set()).add(target)
        backward.setdefault(target, set()).add(source)

    result = set(valid_selected)
    frontier = set(valid_selected)

    for _ in range(steps):
        next_frontier = set()
        for nid in frontier:
            next_frontier.update(forward.get(nid, set()))
            next_frontier.update(backward.get(nid, set()))
        next_frontier -= result
        result.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break

    return result

# --- UI ---
@st.dialog("Image Preview")
def show_image_dialog(image_path: str, prompt_text: str):
    if image_path and os.path.exists(image_path):
        st.image(image_path, width="stretch")
    else:
        st.info("画像はありません")
    st.markdown("**生成ソース:**")
    st.code(prompt_text, language="text")

st.set_page_config(page_title="PromptGraph Lite", layout="wide")

if st.session_state.show_tutorial:
    st.title("PromptGraph Liteへようこそ")

    st.markdown("""
    PromptGraph Liteは、AIイラスト集を読み込み、生成ソースを確認しながら別ルートや続きのイラストを作るためのワークスペースです。

    ---

    ## 基本の流れ

    **新規プロジェクトを作成するか、保存済みプロジェクトを開きます。**
    長く育てるイラスト集はJSONプロジェクトとして保存できます。

    **既存イラスト集を読み込みます。**
    既存のプロンプトTXTと対応する画像をフォルダから読み込めます。

    **イラストを1つ選び、フォーカス編集します。**
    イラストラインから対象を選び、別ルートのイラストや、このルートの次のイラストを作成します。

    **候補イラストを生成・比較し、採用結果を残します。**
    採用イラストや元のイラストを選び、生成ソースをTXTとして出力できます。

    ---

    ## Lite版の制限

    - 編集はフォーカス編集中の1イラストを中心に行います。
    - 一括生成、広範囲の一括編集、Module作成はPro版機能です。
    - グラフとPrompt Cloudは、生成ソースの構造を理解するためのプレビューです。

    ---

    まずはサイドバーの **新規プロジェクトを作る**、**前回のプロジェクトを開く**、または **フォルダから読み込む** から始めてください。

    この案内は **ヘルプ -> 使い方を表示** から再表示できます。
    """)

    if st.button("PromptGraph Liteを始める"):
        st.session_state.show_tutorial = False
        st.rerun()

    st.stop()

st.sidebar.title("PromptGraph Lite")
st.sidebar.caption("AIイラスト集を読み込み、別ルートや続きのイラストを育てます。")

inject_keyboard_shortcuts()
render_shortcut_actions()

st.sidebar.markdown("---")
st.sidebar.subheader("イラスト集ワークスペース")
st.sidebar.warning("まず、新規プロジェクトを作るか、保存済みプロジェクトを開いてください。")

current_project_path = st.session_state.get("current_project_path") or ""
if current_project_path:
    st.sidebar.code(current_project_path, language="text")
elif st.session_state.project:
    st.sidebar.success("未保存のイラスト集ワークスペースを編集中です。")
else:
    st.sidebar.info("プロジェクトはまだ開かれていません。新規作成または保存済みプロジェクトを開いてください。")

overview = project_stats(st.session_state.project)
last_project_path = get_last_project_path(st.session_state.settings)
recent_projects = get_recent_projects(st.session_state.settings)
project_file_default = current_project_path or last_project_path or "project.json"
json_path_default = current_project_path or "project.json"

with st.sidebar.expander("新規プロジェクトを作る", expanded=False):
    st.caption("新しいイラスト集ワークスペースを作成します。project.jsonとgeneratedフォルダを用意します。")
    project_parent_dir = st.text_input("プロジェクトフォルダ", "projects", key="new_project_parent_dir")
    project_name = st.text_input("プロジェクト名", "PromptGraphLiteProject", key="new_project_name")
    if st.button("新規プロジェクトを作る", type="primary", key="create_project_workspace"):
        created, message = create_new_project_workspace(project_parent_dir, project_name)
        if created:
            st.success(message)
            st.rerun()
        else:
            st.warning(message)

if last_project_path:
    st.sidebar.caption("前回のプロジェクトはここから開けます。自動では開きません。")
else:
    st.sidebar.caption("前回のプロジェクトがある場合は、ここから開けます。")
project_cols = st.sidebar.columns(1)
with project_cols[0]:
    if st.button("前回のプロジェクトを開く", disabled=not last_project_path, key="open_last_project"):
        if load_project_json_into_session(last_project_path):
            st.success("プロジェクトを開きました。")
            st.rerun()

with st.sidebar.expander("プロジェクトを開く", expanded=False):
    st.markdown("**最近使ったプロジェクト**")
    if recent_projects:
        recent_options = [item["path"] for item in recent_projects]
        recent_project_path = st.selectbox(
            "最近使ったプロジェクト",
            recent_options,
            format_func=lambda path: next(
                (item["name"] for item in recent_projects if item["path"] == path),
                path,
            ),
            label_visibility="collapsed",
        )
        st.caption(recent_project_path)
        if st.button("最近使ったプロジェクトを開く"):
            if load_project_json_into_session(recent_project_path):
                st.success("プロジェクトを開きました。")
                st.rerun()
    else:
        st.caption("最近使ったプロジェクトはまだありません。")

    st.markdown("**保存済みプロジェクトを開く**")
    open_project_path = st.text_input("プロジェクトJSON", project_file_default, key="open_project_path")
    if st.button("プロジェクトを開く"):
        if load_project_json_into_session(open_project_path):
            st.success("プロジェクトを開きました。")
            st.rerun()

st.sidebar.caption("手動保存です。現在のプロジェクトJSONへ上書き保存します。")
if st.button("プロジェクトを保存", disabled=not bool(st.session_state.project), key="quick_save_project"):
    save_project_to_json(st.session_state.project, json_path_default)
    st.session_state.current_project_path = os.path.abspath(json_path_default)
    ensure_project_folder_layout(st.session_state.current_project_path)
    st.session_state.settings = remember_project(
        st.session_state.settings,
        st.session_state.current_project_path,
    )
    save_settings(st.session_state.settings)
    st.success("プロジェクトを保存しました。")

with st.sidebar.expander("プロジェクトを別名で保存", expanded=False):
    st.caption("現在の保存先とは別のJSONとして手動保存します。自動保存ではありません。")
    json_path = st.text_input("プロジェクトJSON", json_path_default, key="save_project_json_path")
    if st.button("プロジェクトを別名で保存"):
        if st.session_state.project:
            save_project_to_json(st.session_state.project, json_path)
            st.session_state.current_project_path = os.path.abspath(json_path)
            ensure_project_folder_layout(st.session_state.current_project_path)
            st.session_state.settings = remember_project(
                st.session_state.settings,
                st.session_state.current_project_path,
            )
            save_settings(st.session_state.settings)
            st.success("プロジェクトを保存しました。")

with st.sidebar.expander("プロジェクト統計を表示", expanded=bool(st.session_state.project)):
    st.caption("有効なイラスト、別ルート、続き、候補イラスト、採用イラストを確認します。")
    st.caption(f"読み込み元: {overview['source_directory'] or '(未設定)'}")
    st.caption(f"プロジェクトJSON: {current_project_path or '(未保存)'}")
    metric_cols = st.columns(2)
    metric_cols[0].metric("有効なイラスト", overview["active_lines"])
    metric_cols[1].metric("別ルート", overview["branch_lines"])
    metric_cols = st.columns(2)
    metric_cols[0].metric("続き", overview["continued_lines"])
    metric_cols[1].metric("候補イラスト", overview["candidate_images"])
    st.metric("採用イラスト", overview["after_images"])

# Directory loading
st.sidebar.markdown("---")
st.sidebar.subheader("プロジェクトにイラスト集を追加")
st.sidebar.info("手元のイラスト集がある場合は、生成ソース（プロンプト）と画像をフォルダから読み込めます。")
target_dir = st.sidebar.text_input("読み込みフォルダ", st.session_state.settings.get("last_source_directory", "./dummy_data"))

if st.sidebar.button("フォルダから読み込む", key="import_directory"):
    if os.path.isdir(target_dir):
        st.session_state.history = []
        with st.spinner("イラストラインを構築しています..."):
            project = load_directory(target_dir, max_depth=None)
            project = build_graph(project)
        st.session_state.project = project
        st.session_state.current_project_path = ""
        st.session_state.focused_line_id = None
        st.session_state.selected_node_ids = []
        st.session_state.connect_mode = False
        
        st.session_state.settings["last_source_directory"] = target_dir
        save_settings(st.session_state.settings)
        st.sidebar.success(f"読み込みました: {target_dir}")
        st.rerun()
    else:
        st.sidebar.error("フォルダパスが正しくありません。")

if st.sidebar.button(
    "PNGメタデータから読み込む",
    help="生成情報付きPNGから生成ソース（プロンプト）を復元します。",
    key="png_metadata_import",
):
    if os.path.isdir(target_dir):
        if st.session_state.project:
            push_history()
            project = st.session_state.project
        else:
            st.session_state.history = []
            project = Project(source_directory=target_dir)

        with st.spinner("PNGメタデータから生成ソース（プロンプト）を復元しています..."):
            import_summary = add_image_metadata_import(project, target_dir)
            project, line_summary = create_prompt_lines_from_latest_image_import(project)
            project = build_graph(project)

        st.session_state.project = project
        st.session_state.current_project_path = ""
        st.session_state.focused_line_id = None
        st.session_state.selected_node_ids = []
        st.session_state.connect_mode = False
        st.session_state.connect_nodes = []
        st.session_state.settings["last_source_directory"] = target_dir
        save_settings(st.session_state.settings)
        sync_text_areas()

        no_metadata_count = max(import_summary.get("image_count", 0) - import_summary.get("metadata_count", 0), 0)
        st.sidebar.success(
            f"読み込み成功: {line_summary['created_count']}件 / "
            f"スキップ: {line_summary['skipped_count']}件 / "
            f"メタデータなし: {no_metadata_count}件"
        )
        if import_summary.get("warnings"):
            st.sidebar.warning(f"警告: {len(import_summary['warnings'])}件のPNGを確認してください。")
        if line_summary["created_count"] == 0:
            st.sidebar.info("生成ソース（プロンプト）を復元できるPNGメタデータが見つかりませんでした。")
    else:
        st.sidebar.error("フォルダパスが正しくありません。")

st.sidebar.markdown("---")
st.sidebar.subheader("イラスト集の生成ソースを出力")
st.sidebar.warning("プロジェクト保存とは別の出力です。現在のイラスト集から生成ソース（プロンプト）や画像セットを書き出します。")
export_path = st.sidebar.text_input("出力先TXT", st.session_state.settings.get("last_export_path", "prompts.txt"))
if st.sidebar.button("イラストの生成ソース（プロンプト）を出力"):
    if st.session_state.project:
        export_to_txt(st.session_state.project, export_path, disabled_modules=st.session_state.disabled_modules)
        st.session_state.settings["last_export_path"] = export_path
        save_settings(st.session_state.settings)
        st.sidebar.success(f"出力しました: {export_path}")
    else:
        st.sidebar.info("出力するには、先にプロジェクトを作成または読み込んでください。")

with st.sidebar.expander("イラスト・生成ソースセット出力", expanded=False):
    st.caption("プロジェクトJSONは保存せず、利用可能なイラスト画像と生成ソースTXTをセットとして出力します。")
    default_set_export_dir = st.session_state.settings.get("last_export_set_directory", "prompt_image_export")
    export_set_dir = st.text_input("セット出力フォルダ", default_set_export_dir, key="export_prompt_image_set_dir")
    if st.button("イラスト・生成ソースセットを出力", key="export_prompt_image_set"):
        if st.session_state.project:
            summary = export_prompt_image_set(
                st.session_state.project,
                export_set_dir,
                disabled_modules=st.session_state.disabled_modules,
            )
            st.session_state.settings["last_export_set_directory"] = export_set_dir
            save_settings(st.session_state.settings)
            st.sidebar.success(
                f"出力成功: 生成ソース {summary['prompt_count']}件 / "
                f"画像 {summary['image_count']}件 -> {summary['output_dir']}"
            )
            if summary["missing_image_count"]:
                st.sidebar.warning(
                    f"画像が存在しないためプロンプトのみ出力: {summary['missing_image_count']}件"
                )
            if summary["used_fallback_directory"]:
                st.sidebar.info("既存フォルダを上書きしないよう、別名フォルダへ出力しました。")
        else:
            st.sidebar.info("出力するには、先にプロジェクトを作成または読み込んでください。")

st.sidebar.markdown("---")
st.sidebar.subheader("イラストを編集・分岐・継続する")
st.sidebar.info("イラストを選んでフォーカス編集に入り、別ルートや続きのイラストを作成します。")
st.sidebar.markdown("- フォーカス編集\n- 別ルートのイラストを作る\n- このルートの次のイラストを作る\n- 候補イラストを生成する")
edition_label = "PRO" if st.session_state.edition == "PRO" else "FREE"
st.sidebar.write(f"**エディション:** {edition_label}")

scope_mode = "フォーカス編集" if st.session_state.get("focused_line_id") else "全体表示"
st.sidebar.write(f"**編集範囲:** {scope_mode}")

if st.session_state.get("focused_line_id") and st.session_state.project:
    line = next((l for l in st.session_state.project.prompt_lines if l.id == st.session_state.focused_line_id), None)
    if line:
        st.sidebar.caption(f"対象: {line.original_file_name}")
elif is_free():
    st.sidebar.info("イラストラインで対象を選び、フォーカス編集に入ってから分岐・継続してください。")

# Depth calculation (kept internally)

if st.session_state.project and st.session_state.project.prompt_lines:
    max_depth = max([len(l.tokens) for l in st.session_state.project.prompt_lines if not l.deleted], default=1) - 1
else:
    max_depth = 0

if "display_depth" not in st.session_state:
    st.session_state.display_depth = max(0, max_depth)

st.sidebar.markdown("---")
st.sidebar.subheader("イラスト集の構造を理解")
st.sidebar.caption("グラフとPrompt Cloudで、生成ソース（プロンプト）の繰り返し語や構造を確認できます。高度なグラフ編集はPro機能です。")

search_query = st.sidebar.text_input("ノード検索（単語）")
if st.sidebar.button("検索") and search_query:
    if st.session_state.project and st.session_state.project.nodes:
        found_ids = []
        max_found_depth = 0
        for nid, node in st.session_state.project.nodes.items():
            if search_query.lower() in node.display.lower():
                found_ids.append(nid)
                if node.depth > max_found_depth:
                    max_found_depth = node.depth
        
        if found_ids:
            st.session_state.selected_node_ids = found_ids
            st.rerun()
        else:
            st.sidebar.warning("該当するノードはありません。")

focus_mode = st.sidebar.toggle("パスフィルター（選択パスのみ表示）", key="focus_mode")

st.sidebar.markdown("---")
st.sidebar.subheader("グラフ / Prompt Cloud 表示設定")

has_selection = bool(st.session_state.selected_node_ids)

neighborhood_steps = st.sidebar.slider(
    "近傍ステップ",
    min_value=1,
    max_value=5,
    value=st.session_state.get("neighborhood_steps", 2),
    key="neighborhood_steps",
    disabled=not has_selection,
    help="ノード選択時に、選択ノードの前後何ステップまで表示するかを指定します。"
)

if not has_selection:
    st.sidebar.caption("近傍ステップはノード選択後に有効になります。未選択時は初期Root表示です。")

display_depth = st.session_state.get("display_depth", 2)  # kept internally; not shown in UI

if is_free():
    current_merge = getattr(st.session_state.project, "merge_by_word_only", False) if st.session_state.project else False
    merge_preview = st.sidebar.checkbox(
        "同一単語をまとめて表示（Preview）",
        value=current_merge,
        help="Lite版では表示プレビューのみです。同一単語を深さに関係なくまとめたグラフ表示を確認できます。Pro版ではこの統合ビューを使った高速な一括編集が可能です。"
    )
    st.sidebar.caption("Lite版では表示プレビューのみです。Pro版ではこの統合ビューを使った高速な一括編集が可能です。")
    if st.session_state.project and getattr(st.session_state.project, "merge_by_word_only", False) != merge_preview:
        st.session_state.project.merge_by_word_only = merge_preview
        prev_focus = st.session_state.get("focused_line_id")
        st.session_state.project = build_graph(st.session_state.project)
        restore_focus_after_graph_update(prev_focus)
        sync_text_areas()
        st.rerun()
else:
    merge_by_word = st.sidebar.checkbox("同一単語をまとめる（深さを無視）", value=False)
    if st.session_state.project and getattr(st.session_state.project, "merge_by_word_only", False) != merge_by_word:
        st.session_state.project.merge_by_word_only = merge_by_word
        prev_focus = st.session_state.get("focused_line_id")
        st.session_state.project = build_graph(st.session_state.project)
        restore_focus_after_graph_update(prev_focus)
        sync_text_areas()
        st.rerun()

# Connect Mode: shown to all in Focus Edit Mode or Pro; hidden behind expander for Free outside Focus
if is_free() and not st.session_state.get("focused_line_id"):
    with st.sidebar.expander("高度な編集ツール", expanded=False):
        st.checkbox("Connect Mode", value=False, disabled=True, key="_connect_mode_disabled_display")
        st.caption("Connect Modeはフォーカス編集中にのみ使用できます。選択した2つのノードをつなげる編集機能です。")
    # Ensure connect_mode is False while out of focus in FREE
    if st.session_state.connect_mode:
        st.session_state.connect_mode = False
        st.session_state.connect_nodes = []
else:
    connect_mode = st.sidebar.toggle("Connect Mode", value=st.session_state.connect_mode)
    if connect_mode != st.session_state.connect_mode:
        st.session_state.connect_mode = connect_mode
        st.session_state.connect_nodes = []
        st.session_state.selected_node_ids = []
        st.rerun()

# Undo
if st.sidebar.button("元に戻す", disabled=len(st.session_state.history)==0):
    prev_focus = st.session_state.get("focused_line_id")
    undo()
    restore_focus_after_graph_update(prev_focus)
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("Module切り替えプレビュー")
st.sidebar.caption("読み込まれたModuleタグのON/OFF確認用です。Module作成・編集はPro機能です。")
if st.session_state.project:
    available_modules = get_available_modules(st.session_state.project)
    if available_modules:
        for mod_id in available_modules:
            current_val = mod_id not in st.session_state.disabled_modules
            new_val = st.sidebar.checkbox(f"Module {mod_id}", value=current_val, key=f"mod_toggle_{mod_id}")
            if new_val != current_val:
                if new_val:
                    st.session_state.disabled_modules.discard(mod_id)
                else:
                    st.session_state.disabled_modules.add(mod_id)
                st.rerun()
    else:
        st.sidebar.info("Moduleは検出されていません。")
else:
    st.sidebar.info("先にプロジェクトを開くか、フォルダを読み込んでください。")

st.sidebar.markdown("---")
st.sidebar.subheader("ヘルプ")
if st.sidebar.button("使い方を表示"):
    st.session_state.show_tutorial = True
    st.rerun()
st.sidebar.caption("ショートカット案内は現在非表示です。基本操作は画面上のボタンから行ってください。")

if not st.session_state.project:
    st.title("イラスト集ワークスペースを作成")
    st.info("サイドバーから新規プロジェクトを作成するか、保存済みプロジェクトを開いてください。")
    st.markdown("""
    **次にできること**
    - 新しいイラスト集プロジェクトを作成する。
    - 既存のプロンプトや画像がある場合はフォルダから読み込む。
    - 1枚のイラストを起点に、フォーカス編集で別ルートや続きを作る。
    """)
    st.stop()

if not st.session_state.project.prompt_lines:
    st.title("イラスト集ワークスペースを作成しました")
    st.success("空の未保存プロジェクトです。既存イラスト集を読み込むか、このまま新規プロジェクトとして保存できます。")
    st.markdown("""
    **次の操作を選んでください**
    - 既存のプロンプトと画像をフォルダから読み込む。
    - 空のプロジェクト枠として先に保存する。
    - イラストが追加されたら、イラストラインで対象を選び、フォーカス編集・分岐・継続・生成を行う。
    """)
    st.stop()

st.sidebar.markdown("---")
st.sidebar.subheader("生成設定")
st.sidebar.caption("通常は同梱または標準のworkflow_api.jsonを使えます。自分のComfyUIワークフローを使う場合は取扱説明を参照してください。")

def update_comfy_settings():
    st.session_state.settings["comfyui_url"] = st.session_state.comfy_url
    st.session_state.settings["comfyui_workflow_path"] = st.session_state.comfy_workflow_path
    save_settings(st.session_state.settings)

st.session_state.comfy_url = st.sidebar.text_input("ComfyUI URL", st.session_state.settings.get("comfyui_url", "127.0.0.1:8188"), on_change=update_comfy_settings)
st.session_state.comfy_workflow_path = st.sidebar.text_input("workflow_api.jsonパス", st.session_state.settings.get("comfyui_workflow_path", "workflow_api.json"), on_change=update_comfy_settings)

project = st.session_state.project

st.title("PromptGraph Lite")
st.caption("プロジェクト作成 -> 既存イラスト集の読み込み -> フォーカス編集 -> 分岐・継続 -> 保存・出力")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("グラフプレビュー")
    st.caption("生成ソースのつながりや繰り返しを確認し、イラストラインで編集対象を選ぶ参考にします。")
    
    if not hasattr(project, "phrase_freq"):
        project = build_graph(project)
        st.session_state.project = project
        
    # --- Phase 1: determine which nodes to display ---
    # Focus constraint (Focus Edit Mode / Path Filter)
    allowed_by_focus = None
    if st.session_state.get("focused_line_id"):
        target_line = next((l for l in project.prompt_lines if l.id == st.session_state.focused_line_id and not l.deleted), None)
        if target_line:
            allowed_by_focus = set(target_line.node_path)
    elif st.session_state.get("focus_mode", False) and st.session_state.selected_node_ids:
        allowed_by_focus = set()
        for line in project.prompt_lines:
            if not line.deleted:
                if any(nid in line.node_path for nid in st.session_state.selected_node_ids):
                    allowed_by_focus.update(line.node_path)

    # Core display set: selected → neighborhood; unselected → depth ≤ 2
    current_neighborhood_steps = st.session_state.get("neighborhood_steps", neighborhood_steps)
    if st.session_state.selected_node_ids:
        display_node_ids = get_neighborhood_node_ids(
            project,
            st.session_state.selected_node_ids,
            current_neighborhood_steps
        )
        # Fallback: isolated node or empty neighborhood
        if not display_node_ids:
            display_node_ids = set(st.session_state.selected_node_ids)
    else:
        display_node_ids = {nid for nid, n in project.nodes.items() if n.depth <= 2}

    # Apply focus constraint on top
    if allowed_by_focus is not None:
        display_node_ids = display_node_ids & allowed_by_focus

    # --- Phase 2: render nodes from pre-computed set ---
    nodes = []
    displayed_node_ids = set()

    for node_id in display_node_ids:
        if node_id not in project.nodes:
            continue
        node_data = project.nodes[node_id]
        color = "#FF9999" if node_id in st.session_state.selected_node_ids else "#97C2FC"
        nodes.append(Node(id=node_id, label=f"{node_data.display}\n({node_data.count})", size=25, color=color))
        displayed_node_ids.add(node_id)

    # --- Phase 3: render edges between displayed nodes only ---
    edges = []
    for source, target in project.edges:
        if source in displayed_node_ids and target in displayed_node_ids:
            edges.append(Edge(source=source, label="", target=target, type="CURVE_SMOOTH"))

    # Debug: verify Python-side node count changes with Neighborhood Steps
    debug_graph = False
    if debug_graph:
        if st.session_state.selected_node_ids:
            st.caption(f"表示ノード: {len(displayed_node_ids)} / 近傍ステップ: {current_neighborhood_steps}")
        else:
            st.caption(f"表示ノード: {len(displayed_node_ids)} / 初期Root表示")
        
    config = Config(width=600,
                    height=360,
                    directed=True, 
                    physics=False, 
                    hierarchical=True,
                    direction="LR",
                    interaction={"multiselect": True})

    return_value = agraph(nodes=nodes, edges=edges, config=config)
    
    if return_value is not None:
        new_selection = normalize_agraph_selection(return_value, project)
        # Empty list from agraph is treated as a re-render artifact (e.g. Neighborhood Steps change);
        # only update when agraph returns a genuine non-empty selection.
        if new_selection:
            if set(new_selection) != set(st.session_state.selected_node_ids):
                st.session_state.selected_node_ids = new_selection
                added_nodes = new_selection  # all newly selected for connect mode
            
            if st.session_state.connect_mode and new_selection:
                if is_free() and not st.session_state.get("focused_line_id"):
                    st.session_state.connect_nodes = []
                    st.rerun()
                    
                for n in new_selection:
                    if n not in st.session_state.connect_nodes:
                        st.session_state.connect_nodes.append(n)
                        
                if len(st.session_state.connect_nodes) >= 2:
                    source_id = st.session_state.connect_nodes[0]
                    target_id = st.session_state.connect_nodes[1]
                    if target_id in project.nodes:
                        target_word = project.nodes[target_id].display
                        
                        target_lines = None
                        if is_free():
                            target_lines = get_free_target_lines_or_block()
                            if target_lines is None:
                                st.session_state.connect_nodes = []
                                st.rerun()
                        else:
                            target_lines = [st.session_state.focused_line_id] if st.session_state.get("focused_line_id") else None

                        push_history()
                        prev_focus = st.session_state.get("focused_line_id")
                        st.session_state.project = insert_node(st.session_state.project, source_id, target_word, "after", target_lines)
                        restore_focus_after_graph_update(prev_focus)
                        sync_text_areas()
                    st.session_state.connect_nodes = []
                    st.session_state.selected_node_ids = []

            st.rerun()

    st.markdown("---")
    st.markdown("**☁️ Prompt Cloudプレビュー**")
    st.caption("頻出語を選び、どのプロンプト行に現れるかを確認します。編集の起点探しに使います。")
    with st.expander("Word Cloud詳細設定", expanded=False):
        mode = st.radio("WordCloud表示", ["Global", "Graph"], horizontal=True)
        global_group_freq = getattr(project, "global_group_freq", {})
        group_options = ["All"] + list(global_group_freq.keys())
        selected_group = st.selectbox("グループフィルター", group_options)
        analysis_mode = st.radio("スコア方式", ["Raw Count", "Log Scaled", "TF-IDF Score"], horizontal=True)
    
    
    freq = {}
    if mode == "Global":
        if selected_group == "All":
            freq = getattr(project, "phrase_freq", {}).copy()
        else:
            freq = global_group_freq.get(selected_group, {}).copy()
    elif mode == "Graph":
        seen = set()
        for node in project.nodes.values():
            node_group = getattr(node, "group", "default")
            if selected_group == "All" or node_group == selected_group:
                phrase_key = " ".join(sorted(node.phrase))
                if phrase_key in seen:
                    continue
                seen.add(phrase_key)
                freq[phrase_key] = node.count
                
    stopwords = {
        "best quality", "masterpiece", "high quality",
        "1girl", "solo", "looking at viewer",
        "absurdres", "highres", "ultra detailed",
        "illustration", "official art"
    }
    freq = {k: v for k, v in freq.items() if k not in stopwords}
    
    
    import math
    if analysis_mode == "Log Scaled":
        freq = {k: math.log(v + 1) for k, v in freq.items()}
    elif analysis_mode == "TF-IDF Score":
        num_groups = len(global_group_freq)
        if num_groups > 0:
            # 各単語が何グループに出現するかを計算
            word_in_groups = {}
            for g_freq in global_group_freq.values():
                for word in g_freq:
                    word_in_groups[word] = word_in_groups.get(word, 0) + 1
            
            idf_freq = {}
            for k, v in freq.items():
                df = word_in_groups.get(k, 1)
                # idf = log((グループ総数 + 1) / 出現グループ数)
                idf = math.log((num_groups + 1) / df)
                score = v * idf
                if score > 0:
                    idf_freq[k] = score
            freq = idf_freq

    TOP_N = 200
    freq = {k: v for k, v in freq.items() if v > 0}
    freq = dict(sorted(freq.items(), key=lambda x: x[1], reverse=True)[:TOP_N])

    sorted_words = sorted(freq.keys(), key=lambda w: freq[w], reverse=True)
    
    if not freq:
        st.info("現在のフィルターでは表示できるデータがありません。")
        
    if freq:
        
        wc = WordCloud(
            width=800, 
            height=400, 
            background_color="black",
            colormap="viridis",
            max_words=200
        )
        wc.generate_from_frequencies(freq)
        
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.imshow(wc, interpolation="bilinear")
        ax.axis("off")
        fig.tight_layout(pad=0)
        st.pyplot(fig)
            
    phrase_to_nodes = {}
    for node in project.nodes.values():
        key = " ".join(sorted(node.phrase))
        if key not in phrase_to_nodes:
            phrase_to_nodes[key] = []
        phrase_to_nodes[key].append(node.id)
    
    # Word Cloud selection should be non-destructive.
    # Graph selections can include words hidden from Word Cloud by stopwords
    # (e.g. "1girl", "solo"). Do not let Word Cloud widgets clear those selections.
    current_selected_words = []
    current_selected_words_visible = []

    for nid in st.session_state.selected_node_ids:
        if nid in project.nodes:
            key = " ".join(sorted(project.nodes[nid].phrase))
            if key not in current_selected_words:
                current_selected_words.append(key)
            if key in freq and key not in current_selected_words_visible:
                current_selected_words_visible.append(key)

    top_n = 30
    pills_options = sorted_words[:top_n]

    selected_from_pills = st.pills(
        "Prompt Cloud 上位30",
        options=pills_options,
        default=[w for w in current_selected_words_visible if w in pills_options],
        format_func=lambda w: f"{w} ({freq[w]})",
        selection_mode="multi"
    )

    remaining_options = sorted_words[top_n:]
    if remaining_options:
        selected_from_list = st.multiselect(
            "More Words",
            options=remaining_options,
            default=[w for w in current_selected_words_visible if w in remaining_options],
            format_func=lambda w: f"{w} ({freq[w]})"
        )
    else:
        selected_from_list = []

    selected_words_visible = (
        (selected_from_pills if selected_from_pills else [])
        + (selected_from_list if selected_from_list else [])
    )

    # Preserve graph-selected words that are not visible in Word Cloud.
    hidden_selected_words = [
        w for w in current_selected_words
        if w not in freq
    ]

    merged_selected_words = hidden_selected_words + selected_words_visible

    if set(merged_selected_words) != set(current_selected_words):
        new_node_ids = []
        for key in merged_selected_words:
            if key in phrase_to_nodes:
                new_node_ids.extend(phrase_to_nodes[key])
        st.session_state.selected_node_ids = new_node_ids
        st.rerun()
    
    if st.session_state.selected_node_ids:
        st.markdown("---")
        st.markdown("**⚡ フォーカス編集ヘルパー**")
        st.caption("Liteではフォーカス編集中の1イラスト編集が基本です。複数行や構造化された一括操作はPro版機能として制限されます。")

        # Edit Scope Logic
        scope_labels = {
            "focused": "フォーカス中のイラストのみ",
            "global": "全イラスト"
        }
        scope_lookup = {v: k for k, v in scope_labels.items()}
        
        default_scope_key = "focused" if (st.session_state.get("focused_line_id") or is_free()) else "global"
        
        target_scope_label = st.session_state.get("qa_scope_radio", scope_labels[default_scope_key])
        target_scope_key = scope_lookup.get(target_scope_label, default_scope_key)
        
        target_lines = None
        use_global_word_ops = False
        
        if target_scope_key == "focused":
            if st.session_state.get("focused_line_id"):
                target_lines = [st.session_state.focused_line_id]
                use_global_word_ops = True
                st.info("⚠️ 一致する単語をもとに、**フォーカス中のイラスト**だけへ反映します。")
            else:
                if st.session_state.edition == "FREE":
                    st.warning("⚠️ Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                    use_global_word_ops = False
                else:
                    use_global_word_ops = True
                    st.info("⚠️ フォーカス編集ではありません。一致する単語をもとに**全イラスト**へ反映します。")
        elif target_scope_key == "global":
            use_global_word_ops = True
            st.info("⚠️ グラフ表示範囲に関係なく、一致する単語をもとに**全イラスト**へ反映します。")
        else:
            use_global_word_ops = False
            st.info("⚠️ 現在のグラフ表示内にあるノードだけへ反映します。")

        match_mode = "exact"
        if use_global_word_ops:
            match_mode = st.radio("一致条件:", ["exact", "contains"], horizontal=True)
            
            if len(st.session_state.selected_node_ids) == 1:
                nid = st.session_state.selected_node_ids[0]
                if nid in project.nodes:
                    target_word = project.nodes[nid].display
                    match_count = count_matches(st.session_state.project, target_word, target_lines, match_mode)
                    st.info(f"🔍 **プレビュー:** '{target_word}' の一致箇所 {match_count} 件を変更します。")

        if len(st.session_state.selected_node_ids) == 1:
            st.markdown("### 単一ノード操作")
            nid = st.session_state.selected_node_ids[0]
            if nid in project.nodes:
                current_word = project.nodes[nid].display
                col_r1, col_r2 = st.columns([4, 1])
                with col_r1:
                    new_word = st.text_input("Rename", current_word, key=f"qr_{nid}", label_visibility="collapsed", help="ノード名を変更します。カンマや改行は使用できません。")
                    st.caption("入力後、「名前を反映」を押すと反映されます。")
                with col_r2:
                    if st.button("名前を反映", key=f"qr_btn_{nid}"):
                        if not new_word.strip() or "," in new_word or "\n" in new_word:
                            st.warning("🚫 ノード名が空、またはカンマや改行が含まれています。有効な文字を入力してください。")
                            st.stop()
                        
                        if new_word != current_word:
                            if target_scope_key != "focused" and st.session_state.edition == "FREE":
                                show_upgrade_dialog("複数行にわたる一括リネームはPro版の機能です。")
                                st.stop()
                            if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                                st.error("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                                st.stop()
                            
                            push_history()
                            prev_focus = st.session_state.get("focused_line_id")
                            if use_global_word_ops:
                                st.session_state.project = rename_word_global(st.session_state.project, current_word, new_word, target_lines, match_mode)
                            else:
                                st.session_state.project = rename_node(st.session_state.project, nid, new_word, target_lines)
                            restore_focus_after_graph_update(prev_focus)
                            sync_text_areas()
                            st.rerun()
                            

            st.markdown("---")
        st.markdown("**ノードを追加**")
        add_word = st.text_input("追加する単語", key="qa_add_word")
        add_pos = st.radio("位置", ["after", "before"], key="qa_add_pos", horizontal=True, format_func=lambda x: "後" if x == "after" else "前")
        if st.button("ノードを挿入"):
            if add_word:
                if not validate_node_input(add_word):
                    st.stop()

                if target_scope_key != "focused" and st.session_state.edition == "FREE":
                    show_upgrade_dialog("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                    st.stop()

                push_history()
                prev_focus = st.session_state.get("focused_line_id")
                for nid in st.session_state.selected_node_ids:
                    if use_global_word_ops and nid in project.nodes:
                        st.session_state.project = insert_word_global(st.session_state.project, project.nodes[nid].display, add_word, add_pos, target_lines, match_mode)
                    else:
                        st.session_state.project = insert_node(st.session_state.project, nid, add_word, add_pos, target_lines)
                restore_focus_after_graph_update(prev_focus)
                sync_text_areas()
                st.rerun()


        else:
            st.markdown("### 複数ノード操作")
        if st.button("🗑️ ノードを削除"):
            if target_scope_key != "focused" and st.session_state.edition == "FREE":
                show_upgrade_dialog("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                st.stop()
            if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                st.error("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                st.stop()

            push_history()
            prev_focus = st.session_state.get("focused_line_id")
            if use_global_word_ops:
                for nid in st.session_state.selected_node_ids:
                    if nid in project.nodes:
                        st.session_state.project = delete_word_global(st.session_state.project, project.nodes[nid].display, target_lines, match_mode)
            else:
                st.session_state.project = delete_nodes(st.session_state.project, st.session_state.selected_node_ids, target_lines)
            restore_focus_after_graph_update(prev_focus)
            st.session_state.selected_node_ids = []
            sync_text_areas()
            st.rerun()

            st.markdown("---")
        st.markdown("**選択ノードを移動**")
        all_node_options = {nid: n.display for nid, n in project.nodes.items() if nid not in st.session_state.selected_node_ids}
        if all_node_options:
            move_target = st.selectbox("移動先の基準ノード", options=list(all_node_options.keys()), format_func=lambda x: all_node_options[x], key="qa_move_target")
            move_pos = st.radio("移動位置", ["after", "before"], key="qa_move_pos", horizontal=True, format_func=lambda x: "後" if x == "after" else "前")
            if st.button("ノードを移動"):
                if target_scope_key != "focused" and st.session_state.edition == "FREE":
                    show_upgrade_dialog("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                    st.stop()

                push_history()
                prev_focus = st.session_state.get("focused_line_id")
                st.session_state.project = move_nodes(st.session_state.project, st.session_state.selected_node_ids, move_target, move_pos, target_lines)
                restore_focus_after_graph_update(prev_focus)
                sync_text_areas()
                st.rerun()
        else:
            st.info("移動先にできる他のノードがありません。")

        st.markdown("---")
        st.markdown("**⚖️ ウェイト調整**")
        cw1, cw2 = st.columns([3, 1])
        with cw1:
            # We use a static key or no key if it's unique enough. 
            # Since it's only rendered once now, it's fine.
            new_weight = st.slider("ノードウェイト", min_value=0.5, max_value=1.5, value=1.0, step=0.1, key="qa_weight_slider")
        with cw2:
            st.write("") # spacer
            st.write("")
            if st.button("ウェイトを反映", key="qa_weight_btn"):
                effective_targets = target_lines
                if is_free():
                    effective_targets = get_free_target_lines_or_block()
                    if effective_targets is None: st.stop()

                push_history()
                prev_focus = st.session_state.get("focused_line_id")
                st.session_state.project = apply_node_weight(st.session_state.project, st.session_state.selected_node_ids, new_weight, effective_targets)
                restore_focus_after_graph_update(prev_focus)
                sync_text_areas()
                st.rerun()

        st.markdown("---")
        with st.expander("高度な編集 / Pro機能", expanded=False):
            st.markdown("**🎯 編集範囲**")
            st.radio(
                "操作の適用先:",
                options=list(scope_labels.values()),
                index=list(scope_labels.keys()).index(default_scope_key),
                horizontal=True,
                key="qa_scope_radio"
            )

            st.markdown("---")
            mod_name = st.text_input("Module名", key="qa_mod_name")
            if st.button("🧩 Moduleに変換"):
                if st.session_state.edition == "FREE":
                    show_upgrade_dialog("Module作成（ノードを再利用可能なModuleに変換）はPro版機能です。")
                    st.stop()

                if not mod_name.strip():
                    st.warning("Module名を入力してください。")
                    st.stop()

                selected_words = {
                    project.nodes[nid].display
                    for nid in st.session_state.selected_node_ids
                    if nid in project.nodes
                }

                push_history()

                for line in st.session_state.project.prompt_lines:
                    if line.deleted:
                        continue

                    new_tokens = []
                    for token in line.tokens:
                        # ① すでにmodタグならそのまま
                        if token.startswith("<mod:") or token.startswith("</mod:"):
                            new_tokens.append(token)
                            continue
                        # ② 既にラップ済み（安全チェック）
                        if token.startswith(f"<mod:{mod_name}>"):
                            new_tokens.append(token)
                            continue
                        # ③ 対象ワードだけラップ
                        if token in selected_words:
                            new_tokens.append(f"<mod:{mod_name}>")
                            new_tokens.append(token)
                            new_tokens.append(f"</mod:{mod_name}>")
                        else:
                            new_tokens.append(token)

                    line.tokens = new_tokens
                    line.current_text = ", ".join(new_tokens)

                st.session_state.project = build_graph(st.session_state.project)
                sync_text_areas()
                st.rerun()


            st.markdown("---")
            if st.button("📋 ノードを複製"):
                if target_scope_key != "focused" and st.session_state.edition == "FREE":
                    show_upgrade_dialog("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("Lite版ではこの操作にフォーカス編集が必要です。イラストラインで対象を選び、フォーカス編集に入ってから再試行してください。")
                    st.stop()

                push_history()
                prev_focus = st.session_state.get("focused_line_id")
                if use_global_word_ops:
                    for nid in st.session_state.selected_node_ids:
                        if nid in project.nodes:
                            target_word = project.nodes[nid].display
                            st.session_state.project = insert_word_global(st.session_state.project, target_word, target_word, "after", target_lines, match_mode)
                else:
                    st.session_state.project = duplicate_nodes(st.session_state.project, st.session_state.selected_node_ids, target_lines)
                restore_focus_after_graph_update(prev_focus)
                sync_text_areas()
                st.rerun()

            st.markdown("---")
            if st.button("❌ 選択を解除"):
                st.session_state.selected_node_ids = []
                st.rerun()


            st.markdown("---")
            st.markdown("**🌟 お気に入り（スニペット）**")
            fav_name = st.text_input("現在の選択に付ける名前", "お気に入りスニペット")
            if st.button("選択をお気に入りに保存"):
                if not require_pro("再利用スニペットの保存と構造挿入はPro版機能です。"):
                    st.stop()

                nodes = [project.nodes[nid] for nid in st.session_state.selected_node_ids if nid in project.nodes]
                nodes.sort(key=lambda n: n.depth)
                words = [n.display for n in nodes]
                if "favorite_subgraphs" not in st.session_state.settings:
                    st.session_state.settings["favorite_subgraphs"] = []
                st.session_state.settings["favorite_subgraphs"].append({"name": fav_name, "words": words})
                save_settings(st.session_state.settings)
                st.success(f"保存しました: {fav_name}（{len(words)}語）")

            favs = st.session_state.settings.get("favorite_subgraphs", [])
            if favs:
                st.markdown("---")
                fav_options = {i: f"{f['name']}（{len(f['words'])}語）" for i, f in enumerate(favs)}
                sel_fav_idx = st.selectbox("お気に入りを選択", options=list(fav_options.keys()), format_func=lambda x: fav_options[x])
                sel_fav = favs[sel_fav_idx]
                st.caption(", ".join(sel_fav["words"]))

                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    if st.button("➕ 後ろに挿入"):
                        if not require_pro("再利用スニペットと構造挿入はPro版機能です。"):
                            st.stop()

                        push_history()
                        prev_focus = st.session_state.get("focused_line_id")
                        st.session_state.project = insert_subgraph(st.session_state.project, st.session_state.selected_node_ids[-1], sel_fav["words"], "after", target_lines)
                        restore_focus_after_graph_update(prev_focus)
                        sync_text_areas()
                        st.rerun()
                with fc2:
                    if st.button("🔄 置換"):
                        if not require_pro("再利用スニペットと構造挿入はPro版機能です。"):
                            st.stop()

                        push_history()
                        prev_focus = st.session_state.get("focused_line_id")
                        st.session_state.project = replace_with_subgraph(st.session_state.project, st.session_state.selected_node_ids, sel_fav["words"], target_lines)
                        restore_focus_after_graph_update(prev_focus)
                        st.session_state.selected_node_ids = []
                        sync_text_areas()
                        st.rerun()
                with fc3:
                    if st.button("🗑️ お気に入りを削除"):
                        st.session_state.settings["favorite_subgraphs"].pop(sel_fav_idx)
                        save_settings(st.session_state.settings)
                        st.rerun()



with col2:
    tab1, tab2 = st.tabs(["イラストライン", "ノード操作"])

    with tab1:
        st.subheader("イラストライン")
        st.caption("読み込んだイラストと生成ソースを流れとして確認します。別ルートを作る場合は対象を選び、フォーカス編集で調整します。")
        st.caption("各イラストの ↑ / ↓ で順番を調整できます。並べ替えは1件ずつ行うLite-safeな操作です。")
        if st.session_state.get("branch_feedback"):
            st.success(st.session_state.branch_feedback)
            st.session_state.branch_feedback = ""
        
        display_lines = [l for l in project.prompt_lines if not l.deleted]
        
        if st.session_state.selected_node_ids:
            words = [project.nodes[nid].display for nid in st.session_state.selected_node_ids if nid in project.nodes]
            st.info(f"ノードで絞り込み中: **{', '.join(words)}**")
            # 選択中のすべてのノードを含むラインのみ表示するか、いずれかを含むラインを表示するか。
            # 今回はいずれかを含む(OR条件)にする
            display_lines = [l for l in display_lines if any(nid in l.node_path for nid in st.session_state.selected_node_ids)]
        else:
            st.write(f"有効なイラスト: {len(display_lines)}")
        
        if "selected_lines" not in st.session_state:
            st.session_state.selected_lines = {}
            
        c_del, c_dup, c_merge = st.columns([1, 1, 1])
        with c_del:
            if st.button("🗑️ 選択したイラストを削除"):
                if not require_pro("複数イラストの一括操作はPro版機能です。"):
                    st.stop()
                
                push_history()
                to_delete = [lid for lid, checked in st.session_state.selected_lines.items() if checked]
                for lid in to_delete:
                    for line in st.session_state.project.prompt_lines:
                        if line.id == lid:
                            line.deleted = True
                            break
                prev_focus = st.session_state.get("focused_line_id")
                st.session_state.project = build_graph(st.session_state.project)
                restore_focus_after_graph_update(prev_focus)
                st.session_state.selected_node_ids = [nid for nid in st.session_state.selected_node_ids if nid in st.session_state.project.nodes]
                st.session_state.selected_lines = {}
                st.rerun()
        with c_dup:
            if st.button("📋 選択イラストを一括複製（Pro）"):
                if not require_pro("複数イラストの一括操作はPro版機能です。"):
                    st.stop()
                
                push_history()
                to_dup = [lid for lid, checked in st.session_state.selected_lines.items() if checked]
                new_lines = []
                for line in st.session_state.project.prompt_lines:
                    new_lines.append(line)
                    if line.id in to_dup:
                        new_line = copy.deepcopy(line)
                        new_line.id = f"line_{uuid.uuid4().hex[:8]}"
                        new_line.duplicated_from = line.id
                        new_line.edited = True
                        new_lines.append(new_line)
                st.session_state.project.prompt_lines = new_lines
                for i, l in enumerate(st.session_state.project.prompt_lines):
                    l.current_index = i
                prev_focus = st.session_state.get("focused_line_id")
                st.session_state.project = build_graph(st.session_state.project)
                restore_focus_after_graph_update(prev_focus)
                st.session_state.selected_lines = {}
                st.rerun()
        with c_merge:
            if st.button("✨ 重複語を一括整理"):
                if not require_pro("複数イラストの一括操作はPro版機能です。"):
                    st.stop()
                
                push_history()
                prev_focus = st.session_state.get("focused_line_id")
                st.session_state.project = merge_duplicates_all_lines(st.session_state.project)
                restore_focus_after_graph_update(prev_focus)
                st.rerun()
        st.caption("選択イラストの一括操作はPro版候補として表示しており、Liteでは制限されています。")

        st.write("---")
        
        if "focused_line_id" not in st.session_state:
            st.session_state.focused_line_id = None
            
        if st.session_state.focused_line_id:
            target_line = next((l for l in project.prompt_lines if l.id == st.session_state.focused_line_id and not l.deleted), None)
            if not target_line:
                # 行が存在しなくなった場合のみ解除
                st.session_state.focused_line_id = None
                st.rerun()
                
            st.markdown(f"### 🎯 フォーカス編集: `{target_line.original_file_name}`")
            st.caption("フォーカス中の1枚を確認し、生成ソース（プロンプト）の編集、別ルート作成、続きの作成、候補生成を行います。")
            focus_visible_line_ids = [line.id for line in project.prompt_lines if not line.deleted]
            focus_visible_index = focus_visible_line_ids.index(target_line.id)
            c_back, c_up, c_down = st.columns([2, 1, 1])
            with c_back:
                if st.button("🔙 イラストラインに戻る"):
                    st.session_state.focused_line_id = None
                    st.rerun()
            with c_up:
                if st.button("↑", key=f"focus_move_up_{target_line.id}", disabled=focus_visible_index == 0, help="このイラストを前へ移動"):
                    if move_line(target_line.id, focus_visible_line_ids, "up"):
                        st.rerun()
            with c_down:
                if st.button("↓", key=f"focus_move_down_{target_line.id}", disabled=focus_visible_index == len(focus_visible_line_ids) - 1, help="このイラストを後ろへ移動"):
                    if move_line(target_line.id, focus_visible_line_ids, "down"):
                        st.rerun()

            st.markdown("#### 現在のイラスト")
            st.caption("元のイラストと採用イラストを並べて確認します。")
            img_c1, img_c2 = st.columns(2)
            with img_c1:
                st.caption("元のイラスト")
                if target_line.image_path and os.path.exists(target_line.image_path):
                    st.image(target_line.image_path, width="stretch")
                else:
                    st.info("元のイラストはありません。")
            with img_c2:
                st.caption("採用イラスト")
                if getattr(target_line, "generated_image_path", None) and os.path.exists(target_line.generated_image_path):
                    st.image(target_line.generated_image_path, width="stretch")
                else:
                    st.info("採用イラストはまだ選択されていません。")

            st.markdown("#### 生成ソース（プロンプト）")
            st.caption("グラフノードを選択すると、このイラストの生成ソース内で該当語が強調表示されます。")

            highlight_words = [project.nodes[nid].display.lower() for nid in st.session_state.selected_node_ids if nid in project.nodes]

            preview_html = ""
            display_tokens = get_display_tokens(target_line)
            from core.parser import extract_node_metadata
            for token in display_tokens:
                meta = extract_node_metadata(token)
                base = meta["base_word"].lower()
                if base in highlight_words:
                    preview_html += f"<mark style='background-color: #FFD700; font-weight: bold; padding: 2px 4px; border-radius: 4px;'>{token}</mark>, "
                else:
                    preview_html += f"{token}, "
            preview_html = preview_html.strip(", ")
            st.markdown(preview_html, unsafe_allow_html=True)

            edit_panel = st.expander("生成ソース（プロンプト）を編集", expanded=True)
            new_text = edit_panel.text_area("生成ソースを編集", target_line.current_text, key=f"focus_text_{target_line.id}", height=150)
            c1, c2 = edit_panel.columns([1, 1])
            with c1:
                if new_text != target_line.current_text:
                    if st.button("💾 変更を保存", type="primary"):
                        if st.session_state.edition == "FREE":
                            old_structure = extract_module_structure_from_text(target_line.current_text)
                            new_structure = extract_module_structure_from_text(new_text)
                            if old_structure != new_structure:
                                st.error("Lite版ではModuleタグの追加・削除・変更はできません。通常のプロンプト本文だけを編集してください。Module作成・編集はPro版機能です。")
                                st.stop()
                        update_line_text(target_line.id, new_text)
                        st.rerun()
            with c2:
                if st.button("✨ 重複語を整理"):
                    push_history()
                    prev_focus = st.session_state.get("focused_line_id")
                    st.session_state.project = merge_duplicates_in_line(st.session_state.project, target_line.id)
                    restore_focus_after_graph_update(prev_focus)
                    st.rerun()

            with st.expander("生成ソース出力プレビュー（Lite）", expanded=False):
                st.info("現在の生成ソースにModule切り替えなどを反映した、実際に出力・生成へ使われるプロンプトを表示します。")
                from core.operations import get_active_tokens
                fallback_prompt = st.session_state.settings.get("fallback_prompt", "(masterpiece:1.0)")
                current_tokens = get_active_tokens(target_line, st.session_state.disabled_modules, fallback_prompt=fallback_prompt)
                current_generated_text = ", ".join(current_tokens)

                col_diff1, col_diff2 = st.columns(2)
                with col_diff1:
                    st.caption("表示用プロンプト")
                    st.code(", ".join(get_display_tokens_from_text(target_line.current_text)), language="text")
                with col_diff2:
                    st.caption("出力される生成ソース")
                    st.code(current_generated_text, language="text")

                stats = get_structural_stats(target_line.current_text, current_generated_text)
                c_stat1, c_stat2, c_stat3 = st.columns(3)
                c_stat1.metric("トークン差分", f"{stats['token_delta']:+d}")
                c_stat2.metric("有効Module", stats['mod_count'])
                c_stat3.metric("変化率", f"{stats['change_ratio']:.1%}")

                st.markdown("**生成ソースのヒント:**")
                with st.container(border=True):
                    hints = []
                    if stats['mod_count'] > 0:
                        hints.append("- 🧩 **Module検出**: Moduleによる制御やタグ再利用が含まれています。")
                    if abs(stats['token_delta']) > 5:
                        hints.append("- 📏 **長さの変化**: プロンプトの強調バランスが変わる可能性があります。")
                    if stats['has_weights']:
                        hints.append("- ⚖️ **ウェイト**: 出力結果の強さや優先度が変わる可能性があります。")
                    if stats['change_ratio'] > 0.4:
                        hints.append("- 🌊 **変化大**: 元の意図から大きく変わる可能性があります。")

                    if hints:
                        for h in hints:
                            st.markdown(h)
                    else:
                        st.info("構造上の変化は小さめです。")

                st.text_area("最終生成ソース（手動コピー用）", current_generated_text, height=100)
                st.button("📋 クリップボードへコピー", on_click=lambda: components.html(f"<script>navigator.clipboard.writeText('{current_generated_text.replace(chr(39), chr(92)+chr(39))}');</script>", height=0))
                st.caption("Pro版ではコピー＆ペーストなしの直接同期に対応予定です。")

            with st.expander("Moduleタグ付き生成ソース（Debug）", expanded=False):
                st.code(target_line.current_text, language="text")

            st.markdown("#### 別ルート / 続きを作る")
            st.caption("現在のイラストを起点に、別ルートまたはこのルートの次のイラストを作成します。")
            branch_col, continue_col = st.columns(2)
            with branch_col:
                if st.button("🌱 別ルートのイラストを作る", type="primary"):
                    new_line_id = duplicate_line(target_line.id, focus_new_branch=True)
                    if new_line_id:
                        st.session_state.branch_feedback = "フォーカス中のイラストから別ルートを作成しました。"
                    st.rerun()
            with continue_col:
                if st.button("このルートの次のイラストを作る", type="primary"):
                    new_line_id = continue_story_from_line(target_line.id)
                    if new_line_id:
                        st.session_state.branch_feedback = "次のイラストを作成し、フォーカス編集を移動しました。"
                    st.rerun()

            st.markdown("#### 生成・比較")
            st.caption("Liteではフォーカス中の1イラストずつ生成します。一括生成や大規模な生成プールはPro版機能です。")
            if st.button("🎨 ComfyUIで候補イラストを生成", type="primary"):
                try:
                    workflow_json = build_lite_generation_workflow(target_line)
                    output_dir = get_generated_output_dir(st.session_state.project)
                    os.makedirs(output_dir, exist_ok=True)

                    progress_bar = st.progress(0.0)
                    status_text = st.empty()

                    gen_path = None
                    for status in generate_image_with_progress(
                        workflow_json,
                        st.session_state.comfy_url,
                        output_dir,
                        f"gen_{target_line.id}"
                    ):
                        if "value" in status:
                            progress_bar.progress(status["value"])
                        if "text" in status:
                            status_text.markdown(f"**状態:** {status['text']}")
                        if status.get("type") == "done":
                            gen_path = status.get("path")

                    if gen_path:
                        push_history()
                        _append_line_generated_candidates(
                            target_line,
                            _make_generated_candidate_record(gen_path, target_line, "single_generate"),
                        )
                        target_line.generated_image_path = gen_path
                        target_line.selected_candidate_path = gen_path
                        st.success("候補イラストを1枚生成しました。")
                        st.rerun()
                except Exception as e:
                    st.error(f"Liteの単体生成に失敗しました: {e}")

            render_lite_comfy_workflow_debug_preview(target_line)

            st.markdown("#### 候補イラスト管理")
            st.caption("候補を比較し、採用イラストまたは次の生成に使う元のイラストとして設定できます。")
            candidates = list(_get_line_generated_candidates(target_line))
            existing_candidates = [
                candidate
                for candidate in candidates
                if _candidate_path(candidate) and os.path.exists(_candidate_path(candidate))
            ]
            missing_candidates = [
                candidate
                for candidate in candidates
                if _candidate_path(candidate) and not os.path.exists(_candidate_path(candidate))
            ]
            if missing_candidates:
                st.caption(f"保存済み候補パスのうち {len(missing_candidates)} 件が見つかりません。")

            if existing_candidates:
                with st.expander("候補イラスト", expanded=True):
                    for candidate_index, candidate in enumerate(reversed(existing_candidates)):
                        candidate_path = _candidate_path(candidate)
                        st.image(candidate_path, width="stretch")
                        st.caption(candidate_path)
                        ca, cr = st.columns(2)
                        with ca:
                            if st.button("採用イラストにする", key=f"after_{target_line.id}_{candidate_index}"):
                                set_candidate_as_after(target_line, candidate_path)
                                st.success("採用イラストに設定しました。")
                                st.rerun()
                        with cr:
                            if st.button("元のイラストにする", key=f"ref_{target_line.id}_{candidate_index}"):
                                set_candidate_as_reference(target_line, candidate_path)
                                st.success("元のイラストに設定しました。")
                                st.rerun()
            else:
                st.info("候補イラストはまだありません。次のイラスト作成に進む前に候補を生成できます。")
                
        else:
            visible_line_ids = [line.id for line in display_lines]
            for visible_index, l in enumerate(display_lines):
                title = f"[{l.original_file_name}] イラスト {l.original_index}"
                if l.edited:
                    title += "（編集済み）"
                if getattr(l, "continued_from", None):
                    title += "（続き）"
                elif l.duplicated_from:
                    title += "（別ルート）"
                    
                col_chk, col_exp = st.columns([0.05, 0.95])
                with col_chk:
                    st.session_state.selected_lines[l.id] = st.checkbox("選択", value=st.session_state.selected_lines.get(l.id, False), key=f"chk_{l.id}", label_visibility="collapsed")
                
                with col_exp:
                    with st.expander(title):
                        if st.button("🎯 フォーカス編集 / 別ルート", key=f"focus_btn_{l.id}"):
                            st.session_state.focused_line_id = l.id
                            st.rerun()
                            
                        if l.image_path and os.path.exists(l.image_path):
                            c_img, c_txt = st.columns([1, 2])
                            with c_img:
                                st.image(l.image_path, width="stretch")
                            with c_txt:
                                new_text = st.text_area("生成ソース", l.current_text, key=f"text_{l.id}", label_visibility="collapsed")
                        else:
                            new_text = st.text_area("生成ソース", l.current_text, key=f"text_{l.id}")
                            
                        if new_text != l.current_text:
                            if st.button("変更を保存", key=f"save_{l.id}"):
                                if is_free() and not st.session_state.get("focused_line_id"):
                                    st.error("Lite版では編集にフォーカス編集が必要です。フォーカス編集に入ってから編集してください。")
                                    st.stop()
                                update_line_text(l.id, new_text)
                                st.rerun()
                                
                        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
                        if c1.button("↑", key=f"move_up_{l.id}", disabled=visible_index == 0, help="このイラストを前へ移動"):
                            if move_line(l.id, visible_line_ids, "up"):
                                st.rerun()
                        if c2.button("↓", key=f"move_down_{l.id}", disabled=visible_index == len(display_lines) - 1, help="このイラストを後ろへ移動"):
                            if move_line(l.id, visible_line_ids, "down"):
                                st.rerun()
                        if c3.button("別ルート", key=f"dup_{l.id}", help="このイラストの直後に別ルートを作成します"):
                            new_line_id = duplicate_line(l.id)
                            if new_line_id:
                                st.session_state.branch_feedback = "元のイラストの直後に別ルートを作成しました。"
                            st.rerun()
                        if c4.button("削除", key=f"del_{l.id}"):
                            if is_free() and not st.session_state.get("focused_line_id"):
                                st.error("Lite版では編集にフォーカス編集が必要です。フォーカス編集に入ってから編集してください。")
                                st.stop()
                            delete_line(l.id)
                            st.rerun()

    with tab2:
        if st.session_state.connect_mode:
            st.subheader("Connect Mode 有効")
            st.info("グラフ上でノードを2つ順番にクリックして接続します。")
            if len(st.session_state.connect_nodes) == 0:
                st.write("1. 接続元のノードを選択してください...")
            elif len(st.session_state.connect_nodes) == 1:
                nid = st.session_state.connect_nodes[0]
                word = project.nodes[nid].display if nid in project.nodes else nid
                st.write(f"1. 接続元: **{word}**")
                st.write("2. 接続先のノードを選択してください...")
        else:
            st.subheader("ノード操作")
            if not st.session_state.selected_node_ids:
                st.info("グラフ上でノードを選択してください。(Shift/Ctrlクリックで複数選択可能ですが、環境により動作しない場合は一つずつ選択してください)")
            else:
                st.write("選択中のノード:")
                for nid in st.session_state.selected_node_ids:
                    if nid in project.nodes:
                        st.write(f"- **{project.nodes[nid].display}**")
                
                st.markdown("---")
                
                if len(st.session_state.selected_node_ids) == 1:
                    nid = st.session_state.selected_node_ids[0]
                    
                    add_word = st.text_input("追加するノード単語")
                    pos = st.radio("位置", ["Before", "After"], format_func=lambda x: "前" if x == "Before" else "後")
                    if st.button("ノードを追加"):
                        if add_word:
                            if not validate_node_input(add_word):
                                st.stop()
                                
                            effective_targets = None
                            if is_free():
                                effective_targets = get_free_target_lines_or_block()
                                if effective_targets is None: st.stop()
                                
                            push_history()
                            prev_focus = st.session_state.get("focused_line_id")
                            st.session_state.project = insert_node(st.session_state.project, nid, add_word, pos.lower(), effective_targets)
                            restore_focus_after_graph_update(prev_focus)
                            sync_text_areas()
                            st.rerun()
                        
                    st.markdown("---")
                    
                    st.write("**既存ノードをリンク**")
                    existing_options = {n.id: n.display for n in project.nodes.values()}
                    if existing_options:
                        link_target_id = st.selectbox("リンクするノードを選択", options=[""] + list(existing_options.keys()), format_func=lambda x: existing_options[x] if x else "--- ノードを選択 ---")
                        link_pos = st.radio("リンク位置", ["Before", "After"], key="link_pos", format_func=lambda x: "前" if x == "Before" else "後")
                        if st.button("ノードをリンク") and link_target_id:
                            effective_targets = None
                            if is_free():
                                effective_targets = get_free_target_lines_or_block()
                                if effective_targets is None: st.stop()
                                
                            push_history()
                            prev_focus = st.session_state.get("focused_line_id")
                            target_word = project.nodes[link_target_id].display
                            st.session_state.project = insert_node(st.session_state.project, nid, target_word, link_pos.lower(), effective_targets)
                            restore_focus_after_graph_update(prev_focus)
                            sync_text_areas()
                            st.rerun()
                            
                st.markdown("---")
                
                target_options = {n.id: n.display for n in project.nodes.values() if n.id not in st.session_state.selected_node_ids}
                if target_options:
                    target_id = st.selectbox("移動先ノード", options=list(target_options.keys()), format_func=lambda x: target_options[x])
                    move_pos = st.radio("移動位置", ["Before", "After"], key="move_pos", format_func=lambda x: "前" if x == "Before" else "後")
                    if st.button("選択ノードを移動"):
                        effective_targets = None
                        if is_free():
                            effective_targets = get_free_target_lines_or_block()
                            if effective_targets is None: st.stop()
                            
                        push_history()
                        prev_focus = st.session_state.get("focused_line_id")
                        st.session_state.project = move_nodes(st.session_state.project, st.session_state.selected_node_ids, target_id, move_pos.lower(), effective_targets)
                        restore_focus_after_graph_update(prev_focus)
                        st.session_state.selected_node_ids = []
                        sync_text_areas()
                        st.rerun()
                else:
                    st.write("移動先のノードがありません。")
