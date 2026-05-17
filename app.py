import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config
from core.io import load_directory, export_to_txt, save_project_to_json, load_project_from_json
from core.graph_builder import build_graph
from core.operations import rename_node, delete_nodes, insert_node, duplicate_nodes, move_nodes, merge_duplicates_in_line, merge_duplicates_all_lines, apply_node_weight, insert_subgraph, replace_with_subgraph, rename_word_global, delete_word_global, insert_word_global, count_matches, get_available_modules, get_active_tokens, get_display_tokens, get_display_tokens_from_text, extract_module_structure_from_text
from core.parser import parse_prompt
import streamlit.components.v1 as components
import os
import uuid
import copy
import json
from core.comfyui import generate_image_with_progress
from core.settings import load_settings, save_settings, EDITION
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
        st.session_state.shortcut_feedback = "Selection cleared"
        st.rerun()

    if shortcut_undo and st.session_state.history:
        prev_focus = st.session_state.get("focused_line_id")
        undo()
        restore_focus_after_graph_update(prev_focus)
        st.session_state.shortcut_feedback = "Undo"
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
                        st.session_state.shortcut_feedback = "Save blocked"
                        st.error("Free edition cannot change module tags.")
                        st.stop()
                update_line_text(line.id, new_text)
                st.session_state.shortcut_feedback = "Saved focused line"
                st.rerun()
            else:
                st.session_state.shortcut_feedback = "No changes to save"
                st.rerun()
        else:
            st.session_state.shortcut_feedback = "No focused line"
            st.rerun()

    if copy_success:
        st.session_state.shortcut_feedback = "Copied focused line prompt"
        st.rerun()

    if copy_failed:
        st.session_state.shortcut_feedback = "Copy failed"
        st.rerun()

    if focus_editor:
        st.session_state.shortcut_feedback = "Focused line editor"
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

REGULAR_COMFY_WORKFLOW_ERROR = (
    "This appears to be a regular ComfyUI workflow JSON. Please use API-format workflow_api.json "
    "exported with Enable Dev Mode Options → Save (API Format)."
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
        raise ValueError("Workflow JSON is not a ComfyUI API-format workflow with node inputs.")

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
        raise FileNotFoundError(f"Workflow JSON not found at {st.session_state.comfy_workflow_path}")

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
            st.warning("The workflow JSON does not contain '__PROMPT__'. The prompt may not be injected.")
        return workflow_json

    escaped_prompt = json.dumps(", ".join(active_tokens))[1:-1]
    workflow_json = json.loads(wf_str.replace("__PROMPT__", escaped_prompt))
    _validate_api_comfy_workflow(workflow_json)
    return workflow_json

def render_lite_comfy_workflow_debug_preview(target_line):
    with st.expander("Debug: ComfyUI Workflow Preview", expanded=False):
        st.caption("Shared workflow JSON path")
        st.code(st.session_state.comfy_workflow_path or "(not set)", language="text")
        if not os.path.exists(st.session_state.comfy_workflow_path):
            st.warning(f"Workflow JSON not found at {st.session_state.comfy_workflow_path}")
            return
        try:
            workflow_json = build_lite_generation_workflow(target_line)
            st.caption("Final injected API-format workflow JSON")
            st.code(json.dumps(workflow_json, indent=2, ensure_ascii=False), language="json")
        except Exception as exc:
            st.warning(f"Could not build workflow preview: {exc}")

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

@st.dialog("Upgrade to Pro Edition")
def show_upgrade_dialog(message: str):
    st.warning(message)
    st.markdown("""
    ### 🚀 Unlock the Full Power of PromptGraph Pro
    
    The Pro edition is designed for high-velocity workflows and large datasets.
    
    **Pro Features:**
    - **Bulk Editing**: Execute global operations across your entire dataset in one click.
    - **Module Authoring**: Create and save your own reusable prompt modules.
    - **Direct Workflow Sync**: Execute ComfyUI generations directly from the IDE.
    - **Automation Loop**: Auto-rerun workflows as you edit your prompt graph.
    - **Advanced Analytics**: Deep insights into your prompt structure.
    
    [Support on FANBOX & Get Pro](https://example.com/fanbox)
    """)
    if st.button("Close"):
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

def get_free_target_lines_or_block(message: str = "「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」"):
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
        st.info("No Image Available")
    st.markdown("**Prompt:**")
    st.code(prompt_text, language="text")

st.set_page_config(page_title="PromptGraph Lite", layout="wide")

if st.session_state.show_tutorial:
    st.title("🎉 PromptGraph Liteへようこそ！")

    st.markdown("""
    PromptGraph Liteは、既存のAIイラスト資産やプロンプト集を**読み込み、行単位の系譜として編集し、再利用するための入口**です。

    ---

    ## 🧭 基本の流れ

    1. **Import Existing Assets**: 既存の `.txt` と同名画像を読み込みます。
    2. **Prompt Lineage**: Linesでプロンプト行を確認し、編集対象を選びます。
    3. **Focus Edit / Branch Story**: 既存行からBranchを作り、1行ずつ安全に編集します。
    4. **Export / Generate**: Focus Editから1枚ずつ生成し、候補をAfter/Referenceに採用できます。
    5. **Project Management**: JSONで長期作業用に保存・再開します。

    GraphとPrompt Cloudは、プロンプトのつながりやProで広がる編集可能性を確認するプレビューです。

    ---

    ## 🔍 このツールのポイント

    - グラフで単語のつながりが見える
    - Word Cloudで頻出ワードがわかる
    - Active Prompt Previewで結果を確認できる

    ---

    ## ⚠ Free版の制限

    - 一括編集、Module作成、ComfyUIの一括生成はPro機能です
    - LiteではFocus Editを中心に、既存資産を安全に理解・編集します

    ---

    👉 まずはサイドバーの **Import / Load Assets** から始めてください。

    「このチュートリアルは、サイドバーの Help → Show Tutorial からいつでも再表示できます。」
    """)

    if st.button("Start Exploring PromptGraph Lite"):
        st.session_state.show_tutorial = False
        st.rerun()

    st.stop()

st.sidebar.title("PromptGraph Lite")
st.sidebar.caption("既存資産を読み込み、Prompt LineageをFocus Editで安全に分岐・再利用します。")

inject_keyboard_shortcuts()
render_shortcut_actions()

# Directory loading
st.sidebar.markdown("---")
st.sidebar.subheader("1. Import / Load Assets")
st.sidebar.caption("既存のプロンプトTXTと、同名のPNG/JPG画像をプロジェクトとして読み込みます。")
target_dir = st.sidebar.text_input("Source Directory", st.session_state.settings.get("last_source_directory", "./dummy_data"))

if st.sidebar.button("Load Directory"):
    if os.path.isdir(target_dir):
        st.session_state.history = []
        with st.spinner("Building full graph..."):
            project = load_directory(target_dir, max_depth=None)
            project = build_graph(project)
        st.session_state.project = project
        st.session_state.focused_line_id = None
        st.session_state.selected_node_ids = []
        st.session_state.connect_mode = False
        
        st.session_state.settings["last_source_directory"] = target_dir
        save_settings(st.session_state.settings)
        st.sidebar.success(f"Loaded from {target_dir}")
    else:
        st.sidebar.error("Invalid directory path")

st.sidebar.markdown("---")
st.sidebar.subheader("Lite Workflow Status")
edition_label = "💎 PRO" if st.session_state.edition == "PRO" else "🆓 FREE"
st.sidebar.write(f"**Edition:** {edition_label}")

scope_mode = "🎯 Focus Edit Mode" if st.session_state.get("focused_line_id") else "🌐 Global View"
st.sidebar.write(f"**Edit Scope:** {scope_mode}")

if st.session_state.get("focused_line_id"):
    line = next((l for l in st.session_state.project.prompt_lines if l.id == st.session_state.focused_line_id), None)
    if line:
        st.sidebar.caption(f"Target: {line.original_file_name}")
elif is_free():
    st.sidebar.info("Liteでは編集対象を1行に絞るFocus Editが基本です。Prompt Lineageから行を選びます。")

st.sidebar.markdown("---")
st.sidebar.subheader("Help")
with st.sidebar.expander("Keyboard Shortcuts", expanded=False):
    st.markdown("- `Esc`: Clear graph selection")
    st.markdown("- `Ctrl/Cmd+Z`: Undo when not typing")
    st.markdown("- `Ctrl/Cmd+S`: Save focused line")
    st.markdown("- `Enter` / `F2`: Focus the line editor")
    st.markdown("- `Ctrl/Cmd+C`: Copy focused line prompt")
    if is_free():
        st.caption("Lite-safe: shortcuts are mainly for Focus Edit Mode / one-line editing. Global editing remains restricted.")
    else:
        st.caption("Safe v1 shortcuts only. Destructive global shortcuts are not enabled.")

if st.session_state.get("shortcut_feedback"):
    st.sidebar.caption(f"Shortcut: {st.session_state.shortcut_feedback}")

if st.sidebar.button("📘 Show Tutorial"):
    st.session_state.show_tutorial = True
    st.rerun()

st.sidebar.caption("基本操作：Import → Prompt Lineage → Focus Edit → Export / Project Save")

# Depth calculation (kept internally)

if st.session_state.project and st.session_state.project.prompt_lines:
    max_depth = max([len(l.tokens) for l in st.session_state.project.prompt_lines if not l.deleted], default=1) - 1
else:
    max_depth = 0

if "display_depth" not in st.session_state:
    st.session_state.display_depth = max(0, max_depth)

st.sidebar.markdown("---")
st.sidebar.subheader("6. Graph / Prompt Cloud Preview")
st.sidebar.caption("可視化はLiteの理解補助です。広範囲の構造編集はProの領域です。")

search_query = st.sidebar.text_input("Search Node (Word)")
if st.sidebar.button("Search") and search_query:
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
            st.sidebar.warning("No nodes found.")

focus_mode = st.sidebar.toggle("Path Filter (Show Selected Paths Only)", key="focus_mode")

st.sidebar.markdown("---")
st.sidebar.subheader("Graph Preview Settings")

has_selection = bool(st.session_state.selected_node_ids)

neighborhood_steps = st.sidebar.slider(
    "Neighborhood Steps",
    min_value=1,
    max_value=5,
    value=st.session_state.get("neighborhood_steps", 2),
    key="neighborhood_steps",
    disabled=not has_selection,
    help="ノード選択時に、選択ノードの前後何ステップまで表示するかを指定します。"
)

if not has_selection:
    st.sidebar.caption("Neighborhood Stepsはノード選択後に有効になります。未選択時は初期Root表示です。")

display_depth = st.session_state.get("display_depth", 2)  # kept internally; not shown in UI

if is_free():
    current_merge = getattr(st.session_state.project, "merge_by_word_only", False) if st.session_state.project else False
    merge_preview = st.sidebar.checkbox(
        "Merge Identical Words Preview",
        value=current_merge,
        help="Free版では表示プレビューのみです。同一単語を深さに関係なくまとめたグラフ表示を確認できます。Pro版ではこの統合ビューを使った高速な一括編集が可能です。"
    )
    st.sidebar.caption("Free版では表示プレビューのみです。Pro版ではこの統合ビューを使った高速な一括編集が可能です。")
    if st.session_state.project and getattr(st.session_state.project, "merge_by_word_only", False) != merge_preview:
        st.session_state.project.merge_by_word_only = merge_preview
        prev_focus = st.session_state.get("focused_line_id")
        st.session_state.project = build_graph(st.session_state.project)
        restore_focus_after_graph_update(prev_focus)
        sync_text_areas()
        st.rerun()
else:
    merge_by_word = st.sidebar.checkbox("Merge Identical Words (Ignore Depth)", value=False)
    if st.session_state.project and getattr(st.session_state.project, "merge_by_word_only", False) != merge_by_word:
        st.session_state.project.merge_by_word_only = merge_by_word
        prev_focus = st.session_state.get("focused_line_id")
        st.session_state.project = build_graph(st.session_state.project)
        restore_focus_after_graph_update(prev_focus)
        sync_text_areas()
        st.rerun()

# Connect Mode: shown to all in Focus Edit Mode or Pro; hidden behind expander for Free outside Focus
if is_free() and not st.session_state.get("focused_line_id"):
    with st.sidebar.expander("Advanced Edit Tools", expanded=False):
        st.checkbox("Connect Mode", value=False, disabled=True, key="_connect_mode_disabled_display")
        st.caption("Connect ModeはFocus Edit Mode中にのみ使用できます。選択した2つのノードをつなげる編集機能です。")
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
if st.sidebar.button("Undo", disabled=len(st.session_state.history)==0):
    prev_focus = st.session_state.get("focused_line_id")
    undo()
    restore_focus_after_graph_update(prev_focus)
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("Module Toggles Preview")
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
        st.sidebar.info("No modules detected.")
else:
    st.sidebar.info("Load project first.")

st.sidebar.markdown("---")
# Export/Save
st.sidebar.subheader("4. Export / Generate Result")
# TODO: Add export modes: combined TXT / overwrite original files / write to separate output directory
# 「Free版でのExport/Save許可はプレ公開方針。必要なら後で制限する。」
export_path = st.sidebar.text_input("Export Combined TXT Path", st.session_state.settings.get("last_export_path", "prompts.txt"))
st.sidebar.caption("現在は全プロンプトを1つのTXTにまとめて書き出します。元ファイル上書き/個別ファイル出力は今後対応予定です。")
if st.sidebar.button("Export Combined TXT"):
    if st.session_state.project:
        export_to_txt(st.session_state.project, export_path, disabled_modules=st.session_state.disabled_modules)
        st.session_state.settings["last_export_path"] = export_path
        save_settings(st.session_state.settings)
        st.sidebar.success(f"Exported to {export_path}")

st.sidebar.caption("Lite supports single-image generation from Focus Edit. Batch generation remains a Pro feature.")

st.sidebar.markdown("---")
st.sidebar.subheader("5. Project Management")
json_path = st.sidebar.text_input("Save Project (JSON)", "project.json")
col_s1, col_s2 = st.sidebar.columns(2)
with col_s1:
    # 「Free版でのExport/Save許可はプレ公開方針。必要なら後で制限する。」
    if st.button("Save JSON"):
        if st.session_state.project:
            save_project_to_json(st.session_state.project, json_path)
            st.success("Project saved.")
with col_s2:
    if st.button("Load JSON"):
        if os.path.exists(json_path):
            st.session_state.history = []
            project = load_project_from_json(json_path)
            project = build_graph(project)
            st.session_state.project = project
            st.session_state.focused_line_id = None
            st.session_state.selected_node_ids = []
            st.session_state.connect_mode = False
            st.success("Project loaded.")
        else:
            st.error("File not found")

if not st.session_state.project:
    st.info("Start with Import / Load Assets in the sidebar, or load a saved project JSON from Project Management.")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.subheader("Generate Settings")
st.sidebar.caption("Used by Lite single-candidate generation. Batch and automation loops remain Pro-only.")

def update_comfy_settings():
    st.session_state.settings["comfyui_url"] = st.session_state.comfy_url
    st.session_state.settings["comfyui_workflow_path"] = st.session_state.comfy_workflow_path
    save_settings(st.session_state.settings)

st.session_state.comfy_url = st.sidebar.text_input("ComfyUI URL", st.session_state.settings.get("comfyui_url", "127.0.0.1:8188"), on_change=update_comfy_settings)
st.session_state.comfy_workflow_path = st.sidebar.text_input("Workflow JSON Path", st.session_state.settings.get("comfyui_workflow_path", "workflow_api.json"), on_change=update_comfy_settings)

project = st.session_state.project

st.title("PromptGraph Lite Workflow")
st.caption("Import existing assets → Edit prompt lineage → Export/regenerate → Manage project → Preview graph and prompt cloud potential.")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Graph Preview")
    st.caption("Inspect lineage and repeated prompt structure. Use Prompt Lineage for Lite editing decisions.")
    
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
            st.caption(f"Displayed nodes: {len(displayed_node_ids)} / Neighborhood Steps: {current_neighborhood_steps}")
        else:
            st.caption(f"Displayed nodes: {len(displayed_node_ids)} / Initial Root View")
        
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
    st.markdown("**☁️ Prompt Cloud Preview**")
    st.caption("頻出語を選び、どのプロンプト行に現れるかを確認します。編集の起点探しに使います。")
    with st.expander("Advanced Word Cloud Settings", expanded=False):
        mode = st.radio("WordCloud Mode", ["Global", "Graph"], horizontal=True)
        global_group_freq = getattr(project, "global_group_freq", {})
        group_options = ["All"] + list(global_group_freq.keys())
        selected_group = st.selectbox("Group Filter", group_options)
        analysis_mode = st.radio("Scoring Method", ["Raw Count", "Log Scaled", "TF-IDF Score"], horizontal=True)
    
    
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
        st.info("No data for current filter")
        
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
        "Prompt Cloud (Top 30)",
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
        st.markdown("**⚡ Focus Edit Helpers**")
        st.caption("LiteではFocus Edit中の1行編集が基本です。複数行や構造化された一括操作はPro機能として制限されます。")

        # Edit Scope Logic
        scope_labels = {
            "focused": "Focused Line Only",
            "global": "Global (All Lines)"
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
                st.info("⚠️ Operations will apply to the **focused line** based on matching words.")
            else:
                if st.session_state.edition == "FREE":
                    st.warning("⚠️ 「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
                    use_global_word_ops = False
                else:
                    use_global_word_ops = True
                    st.info("⚠️ Focus mode is not active. Applying globally to **all lines** based on matching words.")
        elif target_scope_key == "global":
            use_global_word_ops = True
            st.info("⚠️ Operations will apply globally to **all lines** based on matching words, ignoring graph limits.")
        else:
            use_global_word_ops = False
            st.info("⚠️ Operations will apply STRICTLY to nodes visible in the current graph view.")

        match_mode = "exact"
        if use_global_word_ops:
            match_mode = st.radio("Match Mode:", ["exact", "contains"], horizontal=True)
            
            if len(st.session_state.selected_node_ids) == 1:
                nid = st.session_state.selected_node_ids[0]
                if nid in project.nodes:
                    target_word = project.nodes[nid].display
                    match_count = count_matches(st.session_state.project, target_word, target_lines, match_mode)
                    st.info(f"🔍 **Preview:** Will modify {match_count} occurrences of '{target_word}'.")

        if len(st.session_state.selected_node_ids) == 1:
            st.markdown("### 単一ノード操作")
            nid = st.session_state.selected_node_ids[0]
            if nid in project.nodes:
                current_word = project.nodes[nid].display
                col_r1, col_r2 = st.columns([4, 1])
                with col_r1:
                    new_word = st.text_input("Rename", current_word, key=f"qr_{nid}", label_visibility="collapsed", help="ノード名を変更します。カンマや改行は使用できません。")
                    st.caption("入力後、Apply Renameを押すと反映されます。")
                with col_r2:
                    if st.button("Apply Rename", key=f"qr_btn_{nid}"):
                        if not new_word.strip() or "," in new_word or "\n" in new_word:
                            st.warning("🚫 ノード名が空、またはカンマや改行が含まれています。有効な文字を入力してください。")
                            st.stop()
                        
                        if new_word != current_word:
                            if target_scope_key != "focused" and st.session_state.edition == "FREE":
                                show_upgrade_dialog("複数行にわたる一括リネームはPro版の機能です。")
                                st.stop()
                            if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                                st.error("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
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
        st.markdown("**Add Node**")
        add_word = st.text_input("New word to insert", key="qa_add_word")
        add_pos = st.radio("Position", ["after", "before"], key="qa_add_pos", horizontal=True)
        if st.button("Insert Node"):
            if add_word:
                if not validate_node_input(add_word):
                    st.stop()

                if target_scope_key != "focused" and st.session_state.edition == "FREE":
                    show_upgrade_dialog("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
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
        if st.button("🗑️ Delete Node"):
            if target_scope_key != "focused" and st.session_state.edition == "FREE":
                show_upgrade_dialog("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
                st.stop()
            if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                st.error("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
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
        st.markdown("**Move Selected Nodes**")
        all_node_options = {nid: n.display for nid, n in project.nodes.items() if nid not in st.session_state.selected_node_ids}
        if all_node_options:
            move_target = st.selectbox("Move relative to:", options=list(all_node_options.keys()), format_func=lambda x: all_node_options[x], key="qa_move_target")
            move_pos = st.radio("Move Position", ["after", "before"], key="qa_move_pos", horizontal=True)
            if st.button("Move Nodes"):
                if target_scope_key != "focused" and st.session_state.edition == "FREE":
                    show_upgrade_dialog("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
                    st.stop()

                push_history()
                prev_focus = st.session_state.get("focused_line_id")
                st.session_state.project = move_nodes(st.session_state.project, st.session_state.selected_node_ids, move_target, move_pos, target_lines)
                restore_focus_after_graph_update(prev_focus)
                sync_text_areas()
                st.rerun()
        else:
            st.info("No other nodes to move to.")

        st.markdown("---")
        st.markdown("**⚖️ Weight Adjustment**")
        cw1, cw2 = st.columns([3, 1])
        with cw1:
            # We use a static key or no key if it's unique enough. 
            # Since it's only rendered once now, it's fine.
            new_weight = st.slider("Node Weight", min_value=0.5, max_value=1.5, value=1.0, step=0.1, key="qa_weight_slider")
        with cw2:
            st.write("") # spacer
            st.write("")
            if st.button("Apply Weight", key="qa_weight_btn"):
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
        with st.expander("Advanced / Pro Tools", expanded=False):
            st.markdown("**🎯 Edit Scope**")
            st.radio(
                "Apply operations to:", 
                options=list(scope_labels.values()), 
                index=list(scope_labels.keys()).index(default_scope_key),
                horizontal=True, 
                key="qa_scope_radio"
            )

            st.markdown("---")
            mod_name = st.text_input("Module Name", key="qa_mod_name")
            if st.button("🧩 Convert to Module"):
                if st.session_state.edition == "FREE":
                    show_upgrade_dialog("Module authoring (converting nodes to reusable modules) is available in the Pro edition.")
                    st.stop()

                if not mod_name.strip():
                    st.warning("Module name is required")
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
            if st.button("📋 Duplicate Node"):
                if target_scope_key != "focused" and st.session_state.edition == "FREE":
                    show_upgrade_dialog("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("「Free版ではこの操作にFocus Edit Modeが必要です。Linesタブで対象行を選び、Focus Edit を押してから再試行してください。」")
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
            if st.button("❌ Clear Selection"):
                st.session_state.selected_node_ids = []
                st.rerun()


            st.markdown("---")
            st.markdown("**🌟 Favorites (Snippets)**")
            fav_name = st.text_input("Name for current selection", "My Favorite Snippet")
            if st.button("Save Selection as Favorite"):
                if not require_pro("Saving reusable snippets and structural insertion are Pro features."):
                    st.stop()

                nodes = [project.nodes[nid] for nid in st.session_state.selected_node_ids if nid in project.nodes]
                nodes.sort(key=lambda n: n.depth)
                words = [n.display for n in nodes]
                if "favorite_subgraphs" not in st.session_state.settings:
                    st.session_state.settings["favorite_subgraphs"] = []
                st.session_state.settings["favorite_subgraphs"].append({"name": fav_name, "words": words})
                save_settings(st.session_state.settings)
                st.success(f"Saved: {fav_name} ({len(words)} words)")

            favs = st.session_state.settings.get("favorite_subgraphs", [])
            if favs:
                st.markdown("---")
                fav_options = {i: f"{f['name']} ({len(f['words'])} words)" for i, f in enumerate(favs)}
                sel_fav_idx = st.selectbox("Select Favorite", options=list(fav_options.keys()), format_func=lambda x: fav_options[x])
                sel_fav = favs[sel_fav_idx]
                st.caption(", ".join(sel_fav["words"]))

                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    if st.button("➕ Insert After"):
                        if not require_pro("Reusable snippets and structural insertion are Pro features."):
                            st.stop()

                        push_history()
                        prev_focus = st.session_state.get("focused_line_id")
                        st.session_state.project = insert_subgraph(st.session_state.project, st.session_state.selected_node_ids[-1], sel_fav["words"], "after", target_lines)
                        restore_focus_after_graph_update(prev_focus)
                        sync_text_areas()
                        st.rerun()
                with fc2:
                    if st.button("🔄 Replace"):
                        if not require_pro("Reusable snippets and structural insertion are Pro features."):
                            st.stop()

                        push_history()
                        prev_focus = st.session_state.get("focused_line_id")
                        st.session_state.project = replace_with_subgraph(st.session_state.project, st.session_state.selected_node_ids, sel_fav["words"], target_lines)
                        restore_focus_after_graph_update(prev_focus)
                        st.session_state.selected_node_ids = []
                        sync_text_areas()
                        st.rerun()
                with fc3:
                    if st.button("🗑️ Delete Fav"):
                        st.session_state.settings["favorite_subgraphs"].pop(sel_fav_idx)
                        save_settings(st.session_state.settings)
                        st.rerun()



with col2:
    tab1, tab2 = st.tabs(["Prompt Lineage", "Node Operations"])

    with tab1:
        st.subheader("Prompt Lineage")
        st.caption("読み込んだプロンプトを行単位の系譜として確認します。Branchで既存行から派生案を作り、Focus Editで編集します。")
        st.caption("Use ↑ / ↓ on each line to adjust story order. Reorder is single-line and Lite-safe.")
        if st.session_state.get("branch_feedback"):
            st.success(st.session_state.branch_feedback)
            st.session_state.branch_feedback = ""
        
        display_lines = [l for l in project.prompt_lines if not l.deleted]
        
        if st.session_state.selected_node_ids:
            words = [project.nodes[nid].display for nid in st.session_state.selected_node_ids if nid in project.nodes]
            st.info(f"Filtering by node(s): **{', '.join(words)}**")
            # 選択中のすべてのノードを含むラインのみ表示するか、いずれかを含むラインを表示するか。
            # 今回はいずれかを含む(OR条件)にする
            display_lines = [l for l in display_lines if any(nid in l.node_path for nid in st.session_state.selected_node_ids)]
        else:
            st.write(f"Total Lines: {len(display_lines)}")
        
        if "selected_lines" not in st.session_state:
            st.session_state.selected_lines = {}
            
        c_del, c_dup, c_merge = st.columns([1, 1, 1])
        with c_del:
            if st.button("🗑️ Delete Selected Lines"):
                if not require_pro("Batch line operations are available in Pro."):
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
            if st.button("📋 Batch Duplicate Selected Lines (Pro)"):
                if not require_pro("Batch line operations are available in Pro."):
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
            if st.button("✨ Merge All Duplicates"):
                if not require_pro("Batch line operations are available in Pro."):
                    st.stop()
                
                push_history()
                prev_focus = st.session_state.get("focused_line_id")
                st.session_state.project = merge_duplicates_all_lines(st.session_state.project)
                restore_focus_after_graph_update(prev_focus)
                st.rerun()
        st.caption("Selected-line batch operations are shown as Pro potential and remain restricted in Lite.")

        st.write("---")
        
        if "focused_line_id" not in st.session_state:
            st.session_state.focused_line_id = None
            
        if st.session_state.focused_line_id:
            target_line = next((l for l in project.prompt_lines if l.id == st.session_state.focused_line_id and not l.deleted), None)
            if not target_line:
                # 行が存在しなくなった場合のみ解除
                st.session_state.focused_line_id = None
                st.rerun()
                
            st.markdown(f"### 🎯 Focus Edit / Branch Story: `{target_line.original_file_name}`")
            st.caption("この行だけを編集し、Create Branchで分岐し、Continue Storyで次のシーンへ進めます。")
            focus_visible_line_ids = [line.id for line in project.prompt_lines if not line.deleted]
            focus_visible_index = focus_visible_line_ids.index(target_line.id)
            c_back, c_up, c_down = st.columns([2, 1, 1])
            with c_back:
                if st.button("🔙 Back to All Lines"):
                    st.session_state.focused_line_id = None
                    st.rerun()
            with c_up:
                if st.button("↑", key=f"focus_move_up_{target_line.id}", disabled=focus_visible_index == 0, help="Move this focused line earlier"):
                    if move_line(target_line.id, focus_visible_line_ids, "up"):
                        st.rerun()
            with c_down:
                if st.button("↓", key=f"focus_move_down_{target_line.id}", disabled=focus_visible_index == len(focus_visible_line_ids) - 1, help="Move this focused line later"):
                    if move_line(target_line.id, focus_visible_line_ids, "down"):
                        st.rerun()
                
            if st.session_state.edition == "FREE":
                st.markdown("---")
                st.markdown("### 📊 Export / Generate Preview (Lite)")
                st.info("このプレビューは、現在の行プロンプトに対してModule Toggleなどを反映した、実際にExportされるプロンプトを表示します。通常のノード編集は保存時点でCurrent Line Promptに反映されるため、差分が小さい場合があります。")
                
                # Get current generated text
                from core.operations import get_active_tokens
                fallback_prompt = st.session_state.settings.get("fallback_prompt", "(masterpiece:1.0)")
                current_tokens = get_active_tokens(target_line, st.session_state.disabled_modules, fallback_prompt=fallback_prompt)
                current_generated_text = ", ".join(current_tokens)
                
                col_diff1, col_diff2 = st.columns(2)
                with col_diff1:
                    st.caption("Display Prompt")
                    st.code(", ".join(get_display_tokens_from_text(target_line.current_text)), language="text")
                with col_diff2:
                    st.caption("Active Export Prompt")
                    st.code(current_generated_text, language="text")
                
                # Structural Stats
                stats = get_structural_stats(target_line.current_text, current_generated_text)
                
                c_stat1, c_stat2, c_stat3 = st.columns(3)
                c_stat1.metric("Token Delta", f"{stats['token_delta']:+d}")
                c_stat2.metric("Active Modules", stats['mod_count'])
                c_stat3.metric("Change Ratio", f"{stats['change_ratio']:.1%}")
                
                st.markdown("**Active Prompt Hints:**")
                with st.container(border=True):
                    hints = []
                    if stats['mod_count'] > 0:
                        hints.append("- 🧩 **Module Detection**: Possible better modular control and tag reuse.")
                    if abs(stats['token_delta']) > 5:
                        hints.append("- 📏 **Length Shift**: Possible significant prompt emphasis shift.")
                    if stats['has_weights']:
                        hints.append("- ⚖️ **Weighting**: Likely strength/priority changes in the output.")
                    if stats['change_ratio'] > 0.4:
                        hints.append("- 🌊 **High Variation**: Transformation may significantly alter the original intent.")
                    
                    if hints:
                        for h in hints: st.markdown(h)
                    else:
                        st.info("Minor structural changes detected.")
                
                st.text_area("Final Modified Prompt (for manual copy)", current_generated_text, height=100)
                st.button("📋 Copy to Clipboard (Auto)", on_click=lambda: components.html(f"<script>navigator.clipboard.writeText('{current_generated_text.replace(chr(39), chr(92)+chr(39))}');</script>", height=0))
                st.caption("Tip: Pro edition allows direct sync without copy-pasting.")

            st.markdown("**Preview (Click graph nodes to highlight):**")
            
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
            
            with st.expander("Raw Prompt with Module Tags (Debug)", expanded=False):
                st.code(target_line.current_text, language="text")
            
            st.markdown("---")
            new_text = st.text_area("Edit Prompt", target_line.current_text, key=f"focus_text_{target_line.id}", height=150)
            c1, c2, c3 = st.columns([1, 1, 1])
            with c1:
                if new_text != target_line.current_text:
                    if st.button("💾 Save Changes", type="primary"):
                        if st.session_state.edition == "FREE":
                            old_structure = extract_module_structure_from_text(target_line.current_text)
                            new_structure = extract_module_structure_from_text(new_text)
                            if old_structure != new_structure:
                                st.error("Free版ではModuleタグの追加・削除・変更はできません。通常のプロンプト本文だけを編集してください。Module作成・編集はPro版機能です。")
                                st.stop()
                        update_line_text(target_line.id, new_text)
                        st.rerun()
            with c2:
                if st.button("🌱 Create Branch from this Line", type="primary"):
                    new_line_id = duplicate_line(target_line.id, focus_new_branch=True)
                    if new_line_id:
                        st.session_state.branch_feedback = "Created a new branch from the focused line."
                    st.rerun()
            with c3:
                if st.button("✨ Merge Duplicate Words"):
                    push_history()
                    prev_focus = st.session_state.get("focused_line_id")
                    st.session_state.project = merge_duplicates_in_line(st.session_state.project, target_line.id)
                    restore_focus_after_graph_update(prev_focus)
                    st.rerun()

            with st.expander("Imported / Generated Image Preview", expanded=False):
                img_c1, img_c2 = st.columns(2)
                with img_c1:
                    st.markdown("**Reference Image**")
                    if target_line.image_path and os.path.exists(target_line.image_path):
                        st.image(target_line.image_path, width="stretch")
                    else:
                        st.info("No reference image.")
                with img_c2:
                    st.markdown("**After Image**")
                    if getattr(target_line, "generated_image_path", None) and os.path.exists(target_line.generated_image_path):
                        st.image(target_line.generated_image_path, width="stretch")
                    else:
                        st.info("No after image selected yet.")

            st.markdown("#### Continue Story")
            st.caption("Create the next story scene from this result.")
            if st.button("Continue Story", type="primary"):
                new_line_id = continue_story_from_line(target_line.id)
                if new_line_id:
                    st.session_state.branch_feedback = "Created the next story line and moved Focus Edit to it."
                st.rerun()

            st.markdown("#### Generate / Compare")
            render_lite_comfy_workflow_debug_preview(target_line)
            st.caption("Lite runs one focused-line generation at a time. Batch generation and scene pools stay Pro-only.")
            if st.button("🎨 Generate with ComfyUI", type="primary"):
                try:
                    workflow_json = build_lite_generation_workflow(target_line)
                    output_dir = os.path.join(st.session_state.project.source_directory or ".", "generated")

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
                            status_text.markdown(f"**Status:** {status['text']}")
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
                        st.success("Generated one candidate image for this prompt line.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Lite single-image generation failed: {e}")

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
                st.caption(f"{len(missing_candidates)} saved candidate path(s) are missing on disk.")

            if existing_candidates:
                with st.expander("Candidate Images", expanded=True):
                    for candidate_index, candidate in enumerate(reversed(existing_candidates)):
                        candidate_path = _candidate_path(candidate)
                        st.image(candidate_path, width="stretch")
                        st.caption(candidate_path)
                        ca, cr = st.columns(2)
                        with ca:
                            if st.button("Set as After", key=f"after_{target_line.id}_{candidate_index}"):
                                set_candidate_as_after(target_line, candidate_path)
                                st.success("Candidate set as After image.")
                                st.rerun()
                        with cr:
                            if st.button("Set as Reference", key=f"ref_{target_line.id}_{candidate_index}"):
                                set_candidate_as_reference(target_line, candidate_path)
                                st.success("Candidate set as Reference image.")
                                st.rerun()
            else:
                st.info("No candidate images yet. Generate one candidate to start the next lineage step.")
                
        else:
            visible_line_ids = [line.id for line in display_lines]
            for visible_index, l in enumerate(display_lines):
                title = f"[{l.original_file_name}] Line {l.original_index}"
                if l.edited:
                    title += " (Edited)"
                if getattr(l, "continued_from", None):
                    title += " (Continued)"
                elif l.duplicated_from:
                    title += " (Branch)"
                    
                col_chk, col_exp = st.columns([0.05, 0.95])
                with col_chk:
                    st.session_state.selected_lines[l.id] = st.checkbox("Select", value=st.session_state.selected_lines.get(l.id, False), key=f"chk_{l.id}", label_visibility="collapsed")
                
                with col_exp:
                    with st.expander(title):
                        if st.button("🎯 Focus Edit / Branch", key=f"focus_btn_{l.id}"):
                            st.session_state.focused_line_id = l.id
                            st.rerun()
                            
                        if l.image_path and os.path.exists(l.image_path):
                            c_img, c_txt = st.columns([1, 2])
                            with c_img:
                                st.image(l.image_path, width="stretch")
                            with c_txt:
                                new_text = st.text_area("Prompt Text", l.current_text, key=f"text_{l.id}", label_visibility="collapsed")
                        else:
                            new_text = st.text_area("Prompt Text", l.current_text, key=f"text_{l.id}")
                            
                        if new_text != l.current_text:
                            if st.button("Save Changes", key=f"save_{l.id}"):
                                if is_free() and not st.session_state.get("focused_line_id"):
                                    st.error("「Free版では編集にFocus Edit Modeが必要です。Focus Edit を押して Focus Edit Modeに入ってから編集してください。」")
                                    st.stop()
                                update_line_text(l.id, new_text)
                                st.rerun()
                                
                        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
                        if c1.button("↑", key=f"move_up_{l.id}", disabled=visible_index == 0, help="Move this prompt line earlier"):
                            if move_line(l.id, visible_line_ids, "up"):
                                st.rerun()
                        if c2.button("↓", key=f"move_down_{l.id}", disabled=visible_index == len(display_lines) - 1, help="Move this prompt line later"):
                            if move_line(l.id, visible_line_ids, "down"):
                                st.rerun()
                        if c3.button("Branch", key=f"dup_{l.id}", help="Create a branch immediately after this prompt line"):
                            new_line_id = duplicate_line(l.id)
                            if new_line_id:
                                st.session_state.branch_feedback = "Created a branch directly after the source line."
                            st.rerun()
                        if c4.button("Delete", key=f"del_{l.id}"):
                            if is_free() and not st.session_state.get("focused_line_id"):
                                st.error("「Free版では編集にFocus Edit Modeが必要です。Focus Edit を押して Focus Edit Modeに入ってから編集してください。」")
                                st.stop()
                            delete_line(l.id)
                            st.rerun()

    with tab2:
        if st.session_state.connect_mode:
            st.subheader("Connect Mode Active")
            st.info("グラフ上でノードを2つ順番にクリックして接続します。")
            if len(st.session_state.connect_nodes) == 0:
                st.write("1. 接続元のノードを選択してください...")
            elif len(st.session_state.connect_nodes) == 1:
                nid = st.session_state.connect_nodes[0]
                word = project.nodes[nid].display if nid in project.nodes else nid
                st.write(f"1. 接続元: **{word}**")
                st.write("2. 接続先のノードを選択してください...")
        else:
            st.subheader("Node Operations")
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
                    
                    add_word = st.text_input("New Node Word")
                    pos = st.radio("Position", ["Before", "After"])
                    if st.button("Add Node"):
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
                    
                    st.write("**Link to Existing Node**")
                    existing_options = {n.id: n.display for n in project.nodes.values()}
                    if existing_options:
                        link_target_id = st.selectbox("Select Node to Link", options=[""] + list(existing_options.keys()), format_func=lambda x: existing_options[x] if x else "--- Select Node ---")
                        link_pos = st.radio("Link Position", ["Before", "After"], key="link_pos")
                        if st.button("Link Node") and link_target_id:
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
                    target_id = st.selectbox("Move Target Node", options=list(target_options.keys()), format_func=lambda x: target_options[x])
                    move_pos = st.radio("Move Position", ["Before", "After"], key="move_pos")
                    if st.button("Move Selected Node(s)"):
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
