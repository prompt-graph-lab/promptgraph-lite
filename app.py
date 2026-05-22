import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config
from core.io import load_directory, export_to_txt, export_prompt_image_set, save_project_to_json, load_project_from_json, add_image_metadata_import, create_prompt_lines_from_latest_image_import, create_project_workspace, ensure_project_folder_layout, project_dir_from_path, resolve_project_image_path, image_path_resolution_attempts, find_image_metadata_for_line
from core.graph_builder import build_graph
from core.operations import rename_node, delete_nodes, insert_node, duplicate_nodes, move_nodes, merge_duplicates_in_line, merge_duplicates_all_lines, apply_node_weight, insert_subgraph, replace_with_subgraph, rename_word_global, delete_word_global, insert_word_global, count_matches, get_available_modules, get_active_tokens, get_display_tokens, get_display_tokens_from_text, extract_module_structure_from_text
from core.parser import parse_prompt
from core.project import Project
import streamlit.components.v1 as components
import os
import uuid
import copy
import json
from datetime import datetime
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
if "last_saved_at" not in st.session_state:
    st.session_state.last_saved_at = ""
if "autosave_feedback" not in st.session_state:
    st.session_state.autosave_feedback = ""
if "pending_focus_action" not in st.session_state:
    st.session_state.pending_focus_action = None
if "selection_mode_enabled" not in st.session_state:
    st.session_state.selection_mode_enabled = False
if "selection_mode_delete_candidates" not in st.session_state:
    st.session_state.selection_mode_delete_candidates = {}
if "gallery_expanded_line_id" not in st.session_state:
    st.session_state.gallery_expanded_line_id = None

def _saved_time_label() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _file_saved_time_label(path: str) -> str:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""

def save_current_project_if_possible(reason: str = "", quiet: bool = False) -> bool:
    project = st.session_state.get("project")
    current_project_path = st.session_state.get("current_project_path") or ""
    if not project:
        if not quiet:
            st.warning("保存するプロジェクトがありません。")
        return False
    if not current_project_path:
        if not quiet:
            st.warning("このプロジェクトはまだ保存先がありません。プロジェクトを別名で保存してください。")
        return False

    save_project_to_json(project, current_project_path)
    st.session_state.current_project_path = os.path.abspath(current_project_path)
    ensure_project_folder_layout(st.session_state.current_project_path)
    st.session_state.settings = remember_project(
        st.session_state.settings,
        st.session_state.current_project_path,
    )
    save_settings(st.session_state.settings)
    st.session_state.last_saved_at = _saved_time_label()
    label = f"自動保存しました: {reason}" if reason else "自動保存しました。"
    if quiet:
        st.session_state.autosave_feedback = label
    else:
        st.success("プロジェクトを保存しました。")
    return True

def autosave_current_project(reason: str = "") -> bool:
    if not st.session_state.get("current_project_path"):
        st.session_state.autosave_feedback = "自動保存: 待機中（保存先なし）"
        return False
    return save_current_project_if_possible(reason=reason, quiet=True)

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
    st.session_state.last_saved_at = ""
    st.session_state.autosave_feedback = "自動保存: 待機中（保存先なし）"

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
    st.session_state.last_saved_at = _saved_time_label()
    st.session_state.autosave_feedback = "自動保存: 有効"
    generated_dir = folders.get("generated") or os.path.join(project_root, "generated")
    return True, f"プロジェクトフォルダを作成しました: {project_root}\nproject.jsonとgeneratedフォルダを作成しました: {generated_dir}"

def get_generated_output_dir(project) -> str:
    source_directory = getattr(project, "source_directory", "") if project else ""
    if source_directory:
        return os.path.join(source_directory, "generated")
    current_project_path = st.session_state.get("current_project_path") or ""
    if current_project_path:
        return os.path.join(project_dir_from_path(current_project_path), "generated")
    return os.path.join(".", "generated")

def _safe_export_project_name(project) -> str:
    current_project_path = st.session_state.get("current_project_path") or ""
    if current_project_path:
        name = os.path.splitext(os.path.basename(current_project_path))[0]
    else:
        source_directory = getattr(project, "source_directory", "") if project else ""
        name = os.path.basename(os.path.abspath(source_directory)) if source_directory else "PromptGraphLiteProject"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name).strip("_") or "PromptGraphLiteProject"

def default_prompt_image_export_dir(project) -> str:
    current_project_path = st.session_state.get("current_project_path") or ""
    if current_project_path:
        return os.path.join(project_dir_from_path(current_project_path), "exports", "prompt_image_export")

    source_directory = getattr(project, "source_directory", "") if project else ""
    if source_directory:
        return os.path.join(os.path.abspath(source_directory), "exports", "prompt_image_export")

    return os.path.join(os.getcwd(), "images", _safe_export_project_name(project), "prompt_image_export")

def export_context_key(project) -> str:
    current_project_path = st.session_state.get("current_project_path") or ""
    if current_project_path:
        return f"project:{os.path.abspath(current_project_path)}"

    source_directory = getattr(project, "source_directory", "") if project else ""
    if source_directory:
        return f"source:{os.path.abspath(source_directory)}"

    return "workspace:unsaved"

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
    st.session_state.last_saved_at = _file_saved_time_label(st.session_state.current_project_path)
    st.session_state.autosave_feedback = "自動保存: 有効"
    return True

def get_line_by_id(project, line_id):
    if not project or not line_id:
        return None
    return next(
        (line for line in project.prompt_lines if line.id == line_id and not getattr(line, "deleted", False)),
        None,
    )

IMPORT_MODE_REPLACE = "上書き読み込み"
IMPORT_MODE_APPEND = "追加読み込み"

def _clear_import_selection_state() -> None:
    st.session_state.focused_line_id = None
    st.session_state.selected_node_ids = []
    st.session_state.connect_mode = False
    st.session_state.connect_nodes = []
    st.session_state.selected_lines = {}

def _imported_lines_for_merge(imported_lines, existing_ids: set[str], start_index: int) -> list:
    merged_lines = []
    next_index = start_index
    for line in imported_lines:
        if getattr(line, "deleted", False):
            continue
        new_line = copy.deepcopy(line)
        base_id = new_line.id or f"imported_line_{next_index}"
        candidate_id = base_id
        suffix = 1
        while candidate_id in existing_ids:
            candidate_id = f"{base_id}_{suffix}"
            suffix += 1
        existing_ids.add(candidate_id)
        new_line.id = candidate_id
        new_line.original_index = next_index
        new_line.current_index = next_index
        merged_lines.append(new_line)
        next_index += 1
    return merged_lines

def _merge_image_import_metadata(target_project, imported_project) -> None:
    imported_metadata = getattr(imported_project, "project_metadata", None)
    imported_image_imports = imported_metadata.get("image_imports", []) if isinstance(imported_metadata, dict) else []
    if not imported_image_imports:
        return
    target_metadata = getattr(target_project, "project_metadata", None)
    if not isinstance(target_metadata, dict):
        target_metadata = {"image_imports": []}
    target_metadata.setdefault("image_imports", []).extend(copy.deepcopy(imported_image_imports))
    target_project.project_metadata = target_metadata

def apply_imported_project(imported_project, import_mode: str, autosave_reason: str) -> None:
    previous_project = st.session_state.get("project")
    previous_project_path = st.session_state.get("current_project_path") or ""
    if previous_project:
        push_history()

    if previous_project:
        project = previous_project
        if not previous_project_path and import_mode == IMPORT_MODE_REPLACE:
            project.source_directory = imported_project.source_directory
    else:
        st.session_state.history = []
        project = Project(source_directory=imported_project.source_directory)

    if import_mode == IMPORT_MODE_APPEND:
        start_index = max((line.current_index for line in project.prompt_lines), default=-1) + 1
        existing_ids = {line.id for line in project.prompt_lines}
        project.prompt_lines.extend(_imported_lines_for_merge(imported_project.prompt_lines, existing_ids, start_index))
    else:
        project.prompt_lines = _imported_lines_for_merge(imported_project.prompt_lines, set(), 0)

    _merge_image_import_metadata(project, imported_project)
    st.session_state.project = build_graph(project)
    st.session_state.current_project_path = previous_project_path
    if not previous_project_path:
        st.session_state.last_saved_at = ""
    _clear_import_selection_state()
    sync_text_areas()
    autosave_current_project(autosave_reason)

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
    autosave_current_project("生成ソースを編集")

def delete_lines(line_ids) -> int:
    target_ids = {line_id for line_id in line_ids if line_id}
    if not target_ids:
        return 0

    existing_target_ids = {
        line.id for line in st.session_state.project.prompt_lines
        if line.id in target_ids and not getattr(line, "deleted", False)
    }
    if not existing_target_ids:
        return 0

    deleted_count = 0
    push_history()
    for line in st.session_state.project.prompt_lines:
        if line.id in existing_target_ids:
            line.deleted = True
            deleted_count += 1

    prev_focus = st.session_state.get("focused_line_id")
    st.session_state.project = build_graph(st.session_state.project)
    restore_focus_after_graph_update(prev_focus)
    # Check if selected nodes still exist
    st.session_state.selected_node_ids = [nid for nid in st.session_state.selected_node_ids if nid in st.session_state.project.nodes]
    st.session_state.selected_lines = {}
    st.session_state.selection_mode_delete_candidates = {}
    if st.session_state.get("gallery_expanded_line_id") in existing_target_ids:
        st.session_state.gallery_expanded_line_id = None
    autosave_current_project("イラストを削除")
    return deleted_count

def delete_line(line_id: str):
    return delete_lines([line_id])

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
    autosave_current_project("差分イラストを作成")
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
    autosave_current_project("このルートの次のイラストを作成")
    return new_line_id

def request_focus_action(action: str, line_id: str) -> None:
    st.session_state.pending_focus_action = {"action": action, "line_id": line_id}

def process_pending_focus_action() -> None:
    pending = st.session_state.get("pending_focus_action")
    if not isinstance(pending, dict):
        return
    st.session_state.pending_focus_action = None
    action = pending.get("action")
    line_id = pending.get("line_id")
    if action == "branch":
        new_line_id = duplicate_line(line_id, focus_new_branch=True)
        if new_line_id:
            st.session_state.branch_feedback = "差分イラストを作成しました。"
            st.rerun()
    elif action == "continue":
        new_line_id = continue_story_from_line(line_id)
        if new_line_id:
            st.session_state.branch_feedback = "このルートの次のイラストを作成しました。"
            st.rerun()

def get_candidate_image_paths(line) -> list[str]:
    return [_candidate_path(candidate) for candidate in _get_line_generated_candidates(line)]

def _existing_project_image_path(path: str, project=None) -> str:
    return resolve_project_image_path(project, path, recursive_basename_search=True)

def _last_image_path_attempt(path: str, project=None) -> str:
    attempts = image_path_resolution_attempts(project, path)
    return attempts[-1] if attempts else ""

def show_missing_image_debug(path: str, project=None) -> None:
    if not path:
        return
    st.caption(f"保存パス: {path}")
    attempted_path = _last_image_path_attempt(path, project)
    if attempted_path:
        st.caption(f"確認パス: {attempted_path}")

def get_line_thumbnail_path(line, project=None) -> str:
    for path in (
        getattr(line, "image_path", None),
        getattr(line, "generated_image_path", None),
    ):
        existing_path = _existing_project_image_path(path, project)
        if existing_path:
            return existing_path
    return ""

def get_line_candidate_items(line, project=None) -> list[tuple[str, str]]:
    items = []
    seen = set()
    for candidate in reversed(list(_get_line_generated_candidates(line))):
        candidate_path = _candidate_path(candidate)
        if not candidate_path or candidate_path in seen:
            continue
        resolved_path = _existing_project_image_path(candidate_path, project)
        if resolved_path:
            items.append((candidate_path, resolved_path))
            seen.add(candidate_path)
    return items

def render_gallery_line_editor(line, project) -> None:
    st.markdown(f"#### 編集: `{line.original_file_name}`")
    edit_text = st.text_area(
        "生成ソース（プロンプト）を直接編集",
        value=getattr(line, "current_text", "") or "",
        key=f"gallery_text_{line.id}",
        height=120,
    )
    action_cols = st.columns([1, 1, 2])
    with action_cols[0]:
        if st.button("保存", key=f"gallery_save_{line.id}", type="primary"):
            update_line_text(line.id, edit_text)
            st.success("生成ソースを保存しました。")
            st.rerun()
    with action_cols[1]:
        if st.button("ComfyUIで単発生成", key=f"gallery_generate_{line.id}", type="primary"):
            try:
                if edit_text != getattr(line, "current_text", ""):
                    update_line_text(line.id, edit_text)
                    line = next(
                        candidate for candidate in st.session_state.project.prompt_lines
                        if candidate.id == line.id
                    )
                workflow_json = build_lite_generation_workflow(line)
                output_dir = get_generated_output_dir(st.session_state.project)
                os.makedirs(output_dir, exist_ok=True)
                progress_bar = st.progress(0.0)
                status_text = st.empty()
                gen_path = None
                for status in generate_image_with_progress(
                    workflow_json,
                    st.session_state.comfy_url,
                    output_dir,
                    f"gen_{line.id}",
                ):
                    if "value" in status:
                        progress_bar.progress(status["value"])
                    if "text" in status:
                        status_text.markdown(f"**状態:** {status['text']}")
                    if status.get("type") == "done":
                        gen_path = status.get("path")
                if gen_path:
                    set_candidate_as_after(line, gen_path)
                    st.success("候補イラストを生成し、出力対象に設定しました。")
                    st.rerun()
            except Exception as exc:
                st.error(f"単発生成に失敗しました: {exc}")
    with action_cols[2]:
        st.caption("生成結果は候補イラストとして保存し、このイラストの出力対象にも設定します。")

    candidate_items = get_line_candidate_items(line, project)
    if candidate_items:
        st.caption("候補イラスト")
        candidate_cols = st.columns(2)
        for index, (stored_path, resolved_path) in enumerate(candidate_items[:4]):
            with candidate_cols[index % 2]:
                st.image(resolved_path, width="stretch")
                is_output = stored_path == getattr(line, "selected_candidate_path", None) or stored_path == getattr(line, "generated_image_path", None)
                st.caption("出力対象" if is_output else "候補")
                if st.button("出力対象にする", key=f"gallery_output_{line.id}_{index}"):
                    set_candidate_as_after(line, stored_path)
                    st.rerun()
    else:
        st.caption("候補イラストはまだありません。")

def render_illustration_selection_mode(project) -> None:
    active_lines = [line for line in project.prompt_lines if not getattr(line, "deleted", False)]
    active_ids = {line.id for line in active_lines}
    visible_line_ids = [line.id for line in active_lines]
    candidates = st.session_state.get("selection_mode_delete_candidates", {})
    if not isinstance(candidates, dict):
        candidates = {}
    candidates = {line_id: bool(value) for line_id, value in candidates.items() if line_id in active_ids}
    for line in active_lines:
        widget_key = f"selection_mode_delete_{line.id}"
        if widget_key in st.session_state:
            candidates[line.id] = bool(st.session_state[widget_key])
    st.session_state.selection_mode_delete_candidates = candidates

    delete_candidate_ids = [line_id for line_id, selected in candidates.items() if selected]
    st.subheader("ギャラリー編集モード")
    st.caption("画像を見ながら順番調整、削除候補の選別、生成ソース編集、単発生成を行います。")
    top_left, top_right = st.columns([1, 1])
    with top_left:
        st.write(f"削除候補: {len(delete_candidate_ids)}件")
        st.caption("元画像ファイルは削除されません。プロジェクト上の一覧から除外します。")
    with top_right:
        if st.button("通常表示に戻る", type="secondary", key="gallery_exit_inside_top"):
            st.session_state.selection_mode_enabled = False
            st.rerun()

    if st.button("削除候補をまとめて削除", type="primary", disabled=not delete_candidate_ids, key="gallery_delete_top"):
        deleted_count = delete_lines(delete_candidate_ids)
        st.session_state.selection_mode_delete_candidates = {}
        if deleted_count:
            st.session_state.branch_feedback = f"{deleted_count}件のイラストを削除しました。"
        st.rerun()

    st.write("---")
    if not active_lines:
        st.info("表示できるイラストがありません。")
        return

    expanded_line_id = st.session_state.get("gallery_expanded_line_id")
    for row_start in range(0, len(active_lines), 4):
        row_lines = active_lines[row_start: row_start + 4]
        cols = st.columns(4)
        for offset, line in enumerate(row_lines):
            line_index = row_start + offset
            with cols[offset]:
                thumbnail_path = get_line_thumbnail_path(line, project)
                if thumbnail_path:
                    st.image(thumbnail_path, width="stretch")
                else:
                    st.info("画像なし")
                st.caption(f"{line.current_index + 1:04d} / {line.original_file_name}")
                prompt_preview = " ".join((getattr(line, "current_text", "") or "").split())
                if prompt_preview:
                    st.caption(prompt_preview[:70] + ("..." if len(prompt_preview) > 70 else ""))
                checked = st.checkbox(
                    "削除候補",
                    value=bool(candidates.get(line.id, False)),
                    key=f"selection_mode_delete_{line.id}",
                )
                st.session_state.selection_mode_delete_candidates[line.id] = checked
                move_cols = st.columns(2)
                with move_cols[0]:
                    if st.button("↑", key=f"gallery_move_up_{line.id}", disabled=line_index == 0, help="前へ"):
                        if move_line(line.id, visible_line_ids, "up"):
                            st.rerun()
                with move_cols[1]:
                    if st.button("↓", key=f"gallery_move_down_{line.id}", disabled=line_index == len(active_lines) - 1, help="次へ"):
                        if move_line(line.id, visible_line_ids, "down"):
                            st.rerun()
                if st.button("編集", key=f"gallery_edit_{line.id}"):
                    st.session_state.gallery_expanded_line_id = None if expanded_line_id == line.id else line.id
                    st.rerun()

        row_expanded = next((line for line in row_lines if line.id == st.session_state.get("gallery_expanded_line_id")), None)
        if row_expanded:
            with st.container(border=True):
                render_gallery_line_editor(row_expanded, project)
                st.caption("将来のルート分岐UIでは、分岐イラストの直前にAルート / Bルートの選択ブロックを置ける構造にします。")

    st.write("---")
    bottom_cols = st.columns([1, 1])
    with bottom_cols[0]:
        if st.button("削除候補をまとめて削除", type="primary", disabled=not delete_candidate_ids, key="gallery_delete_bottom"):
            deleted_count = delete_lines(delete_candidate_ids)
            st.session_state.selection_mode_delete_candidates = {}
            if deleted_count:
                st.session_state.branch_feedback = f"{deleted_count}件のイラストを削除しました。"
            st.rerun()
    with bottom_cols[1]:
        if st.button("通常表示に戻る", key="gallery_exit_bottom"):
            st.session_state.selection_mode_enabled = False
            st.rerun()

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

def _workflow_text_from_line_metadata(project, line):
    image_metadata = find_image_metadata_for_line(project, line)
    raw_metadata = (image_metadata or {}).get("raw_metadata", {})
    if not isinstance(raw_metadata, dict):
        return "", "", image_metadata

    lowered_metadata = {str(key).lower(): value for key, value in raw_metadata.items()}
    for key in ("prompt", "workflow"):
        workflow_text = lowered_metadata.get(key)
        workflow_json = _load_json_from_text(workflow_text) if isinstance(workflow_text, str) else None
        if _is_executable_comfy_workflow(workflow_json):
            return workflow_text, f"PNGメタデータ `{key}`", image_metadata
    return "", "", image_metadata

def _workflow_metadata_status(project, line):
    workflow_text, workflow_label, image_metadata = _workflow_text_from_line_metadata(project, line)
    raw_metadata = (image_metadata or {}).get("raw_metadata", {})
    raw_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    has_prompt = "prompt" in {str(key).lower() for key in raw_metadata}
    has_workflow = "workflow" in {str(key).lower() for key in raw_metadata}
    shared_path = st.session_state.get("comfy_workflow_path") or st.session_state.settings.get("comfyui_workflow_path", "workflow_api.json")
    shared_exists = bool(shared_path and os.path.exists(shared_path))
    if workflow_text:
        selected = f"埋め込みPNG workflowを使用: {workflow_label}"
    elif shared_exists:
        selected = "共有workflow_api.jsonを使用"
    else:
        selected = "実行可能なworkflowが見つかりません"
    return {
        "embedded_found": has_prompt or has_workflow,
        "embedded_executable": bool(workflow_text),
        "workflow_label": workflow_label,
        "shared_path": shared_path,
        "shared_exists": shared_exists,
        "selected": selected,
    }

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

def _replace_clip_text_prompts(workflow_json, line, image_metadata=None):
    if not isinstance(workflow_json, dict):
        return 0

    nodes = workflow_json.get("nodes", workflow_json)
    if not isinstance(nodes, dict):
        return 0

    current_positive = getattr(line, "current_text", "") or ""
    current_negative = getattr(line, "negative_prompt", "") or ""
    imported_positive = (image_metadata or {}).get("prompt_text") or ""
    imported_negative = (image_metadata or {}).get("negative_prompt") or ""
    replacements = 0
    clip_inputs = []
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        if "CLIPTextEncode" not in str(node.get("class_type", "")):
            continue
        inputs = node.get("inputs", {})
        if isinstance(inputs, dict) and isinstance(inputs.get("text"), str):
            clip_inputs.append({"node_id": str(node_id), "inputs": inputs})

    replaced_indexes = set()

    def normalize_prompt_text(value: str) -> str:
        return " ".join(str(value or "").split())

    def replace_clip(index: int, text: str) -> None:
        nonlocal replacements
        if index in replaced_indexes:
            return
        clip_inputs[index]["inputs"]["text"] = text
        replaced_indexes.add(index)
        replacements += 1

    def clip_index_by_node_id(node_id: str | None) -> int | None:
        if not node_id:
            return None
        for index, entry in enumerate(clip_inputs):
            if entry["node_id"] == str(node_id):
                return index
        return None

    def node_link_id(value) -> str | None:
        if isinstance(value, list) and value:
            return str(value[0])
        return None

    def ksampler_clip_roles() -> tuple[int | None, int | None]:
        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            if "KSampler" not in str(node.get("class_type", "")):
                continue
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            positive_index = clip_index_by_node_id(node_link_id(inputs.get("positive")))
            negative_index = clip_index_by_node_id(node_link_id(inputs.get("negative")))
            if positive_index is not None or negative_index is not None:
                return positive_index, negative_index
        return None, None

    for index, entry in enumerate(clip_inputs):
        text = entry["inputs"].get("text", "")
        if imported_positive and text == imported_positive:
            replace_clip(index, current_positive)
        elif imported_negative and text == imported_negative:
            replace_clip(index, current_negative)

    for index, entry in enumerate(clip_inputs):
        if index in replaced_indexes:
            continue
        text = entry["inputs"].get("text", "")
        normalized_text = normalize_prompt_text(text)
        if imported_positive and normalized_text == normalize_prompt_text(imported_positive):
            replace_clip(index, current_positive)
        elif imported_negative and normalized_text == normalize_prompt_text(imported_negative):
            replace_clip(index, current_negative)

    positive_index, negative_index = ksampler_clip_roles()
    if positive_index is not None:
        replace_clip(positive_index, current_positive)
    if negative_index is not None:
        replace_clip(negative_index, current_negative)

    if len(clip_inputs) == 2:
        replace_clip(0, current_positive)
        replace_clip(1, current_negative)
    elif len(clip_inputs) > 2 and not replaced_indexes:
        replace_clip(0, current_positive)
        replace_clip(1, current_negative)
    elif len(clip_inputs) == 1 and not replaced_indexes:
        replace_clip(0, current_positive)

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
    autosave_current_project("候補を出力対象イラストに設定")

def set_candidate_as_reference(line, image_path: str):
    push_history()
    add_candidate_image(line, image_path)
    line.image_path = image_path
    autosave_current_project("候補を元のイラストに設定")

def _build_lite_workflow_from_text(workflow_text, target_line, image_metadata=None):
    mapping = st.session_state.settings.get("comfy_mapping")
    fallback_prompt = st.session_state.settings.get("fallback_prompt", "(masterpiece:1.0)")
    active_tokens = get_active_tokens(target_line, st.session_state.disabled_modules, fallback_prompt=fallback_prompt)
    injection_line = copy.deepcopy(target_line)
    injection_line.current_text = ", ".join(active_tokens)

    if isinstance(mapping, dict) and "group_map" in mapping:
        workflow_json = json.loads(workflow_text)
        _validate_api_comfy_workflow(workflow_json)
        from core.comfyui import build_prompt_by_group, inject_prompt_to_workflow
        grouped = build_prompt_by_group(st.session_state.project, target_line, st.session_state.disabled_modules)
        return inject_prompt_to_workflow(workflow_json, grouped, mapping, fallback_prompt=fallback_prompt)

    if "__PROMPT__" not in workflow_text:
        workflow_json = json.loads(workflow_text)
        _validate_api_comfy_workflow(workflow_json)
        if _replace_clip_text_prompts(workflow_json, injection_line, image_metadata=image_metadata) == 0:
            st.warning("workflow JSONに'__PROMPT__'がありません。プロンプトが反映されない可能性があります。")
        return workflow_json

    escaped_prompt = json.dumps(", ".join(active_tokens))[1:-1]
    workflow_json = json.loads(workflow_text.replace("__PROMPT__", escaped_prompt))
    _validate_api_comfy_workflow(workflow_json)
    return workflow_json

def build_lite_generation_workflow(target_line):
    workflow_text, _workflow_label, image_metadata = _workflow_text_from_line_metadata(st.session_state.project, target_line)
    if not workflow_text:
        if not os.path.exists(st.session_state.comfy_workflow_path):
            raise FileNotFoundError(f"workflow JSONが見つかりません: {st.session_state.comfy_workflow_path}")
        with open(st.session_state.comfy_workflow_path, 'r', encoding='utf-8') as f:
            workflow_text = f.read()
    return _build_lite_workflow_from_text(workflow_text, target_line, image_metadata=image_metadata)

def render_lite_comfy_workflow_debug_preview(target_line):
    with st.expander("Debug: ComfyUI workflowプレビュー", expanded=False):
        status = _workflow_metadata_status(st.session_state.project, target_line)
        st.caption("workflowソース状態")
        st.markdown(f"- embedded PNG workflow found: {'yes' if status['embedded_found'] else 'no'}")
        st.markdown(f"- executable embedded workflow: {'yes' if status['embedded_executable'] else 'no'}")
        st.markdown(f"- selected source: {status['selected']}")
        st.caption("共有workflow JSONパス")
        st.code(status["shared_path"] or "(not set)", language="text")
        if not status["embedded_executable"] and not status["shared_exists"]:
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
    autosave_current_project("イラストを並べ替え")
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
    - **効率的な再利用**: 既存の構成や表現を整理し、差分や派生に活用できます。
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

def get_free_target_lines_or_block(message: str = "Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。"):
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
    PromptGraph Liteは、AIイラスト集を読み込み、生成ソースを確認しながら差分や続きのイラストを作るためのプロジェクトです。

    ---

    ## 基本の流れ

    **新規プロジェクトを作成するか、保存済みプロジェクトを開きます。**
    長く育てるイラスト集はJSONプロジェクトとして保存できます。

    **既存イラスト集を読み込みます。**
    既存のプロンプトTXTと対応する画像をフォルダから読み込めます。

    **イラストを1つ選び、生成ソース（プロンプト）を編集します。**
    イラスト一覧から対象を選び、差分イラストや、このルートの次のイラストを作成します。

    **候補イラストを生成・比較し、出力対象イラストを残します。**
    出力対象イラストや元のイラストを選び、生成ソースをTXTとして出力できます。

    ---

    ## Lite版の制限

    - 編集は選択中の1イラストを中心に行います。
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
st.sidebar.caption("AIイラスト集を読み込み、差分や続きのイラストを育てます。")

inject_keyboard_shortcuts()
render_shortcut_actions()

st.sidebar.markdown("---")
st.sidebar.subheader("プロジェクト")
st.sidebar.warning("まず、新規プロジェクトを作るか、保存済みプロジェクトを開いてください。")

current_project_path = st.session_state.get("current_project_path") or ""
overview = project_stats(st.session_state.project)
last_project_path = get_last_project_path(st.session_state.settings)
recent_projects = get_recent_projects(st.session_state.settings)
project_file_default = current_project_path or last_project_path or "project.json"
json_path_default = current_project_path or "project.json"

with st.sidebar.container(border=True):
    st.markdown("#### 📁 現在のプロジェクト")
    if current_project_path:
        st.code(current_project_path, language="text")
    elif st.session_state.project:
        st.success("未保存のプロジェクトを編集中です。")
    else:
        st.info("プロジェクトはまだ開かれていません。")

    st.markdown(f"**最終保存:** {st.session_state.last_saved_at or '(まだ保存されていません)'}")
    autosave_status = "有効" if current_project_path else "待機中（保存先なし）"
    st.markdown(f"**自動保存:** {autosave_status}")
    if st.session_state.autosave_feedback:
        st.caption(st.session_state.autosave_feedback)

with st.sidebar.expander("プロジェクトの新規作成", expanded=False):
    st.caption("新しいプロジェクトを作成します。project.jsonとgeneratedフォルダを用意します。")
    project_parent_dir = st.text_input("プロジェクトフォルダ", "projects", key="new_project_parent_dir")
    project_name = st.text_input("プロジェクト名", "PromptGraphLiteProject", key="new_project_name")
    if st.button("新規プロジェクトを作る", type="primary", key="create_project_workspace"):
        created, message = create_new_project_workspace(project_parent_dir, project_name)
        if created:
            st.success(message)
            st.rerun()
        else:
            st.warning(message)

with st.sidebar.expander("プロジェクトを開く", expanded=False):
    st.markdown("**前回のプロジェクト**")
    if last_project_path:
        st.caption(last_project_path)
    else:
        st.caption("前回のプロジェクトはまだありません。")
    if st.button("前回のプロジェクトを開く", disabled=not last_project_path, key="open_last_project"):
        if load_project_json_into_session(last_project_path):
            st.success("プロジェクトを開きました。")
            st.rerun()

    st.markdown("**最近のプロジェクト**")
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

    st.markdown("**指定のプロジェクト**")
    open_project_path = st.text_input("プロジェクトJSON", project_file_default, key="open_project_path")
    if st.button("プロジェクトを開く"):
        if load_project_json_into_session(open_project_path):
            st.success("プロジェクトを開きました。")
            st.rerun()

with st.sidebar.expander("プロジェクトを保存", expanded=False):
    st.markdown("**上書き保存**")
    st.caption("現在のプロジェクトJSONへ手動保存します。")
    if st.button("💾 現在のプロジェクトを保存", disabled=not bool(st.session_state.project), key="quick_save_project", type="primary"):
        save_current_project_if_possible()

    st.markdown("**別名保存**")
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
            st.session_state.last_saved_at = _saved_time_label()
            st.session_state.autosave_feedback = "自動保存: 有効"
            st.success("プロジェクトを保存しました。")

with st.sidebar.expander("プロジェクトの統計", expanded=bool(st.session_state.project)):
    st.caption("有効なイラスト、差分、続き、候補イラスト、出力対象イラストを確認します。")
    st.caption(f"読み込み元: {overview['source_directory'] or '(未設定)'}")
    st.caption(f"プロジェクトJSON: {current_project_path or '(未保存)'}")
    metric_cols = st.columns(2)
    metric_cols[0].metric("有効なイラスト", overview["active_lines"])
    metric_cols[1].metric("差分", overview["branch_lines"])
    metric_cols = st.columns(2)
    metric_cols[0].metric("続き", overview["continued_lines"])
    metric_cols[1].metric("候補イラスト", overview["candidate_images"])
    st.metric("出力対象イラスト", overview["after_images"])

# Directory loading
st.sidebar.markdown("---")
st.sidebar.subheader("プロジェクトにイラスト集を追加")
st.sidebar.info("手元のイラスト集がある場合は、生成ソース（プロンプト）と画像をフォルダから読み込めます。")
target_dir = st.sidebar.text_input("読み込みフォルダ", st.session_state.settings.get("last_source_directory", "./dummy_data"))
import_mode = st.sidebar.radio(
    "読み込み方法",
    [IMPORT_MODE_REPLACE, IMPORT_MODE_APPEND],
    index=0,
    key="lite_import_mode",
)
st.sidebar.caption("上書き読み込み：現在のイラスト一覧を置き換えます")
st.sidebar.caption("追加読み込み：現在のイラスト一覧の末尾に追加します")

if st.sidebar.button("フォルダから読み込む", key="import_directory"):
    if os.path.isdir(target_dir):
        with st.spinner("イラスト一覧を構築しています..."):
            imported_project = load_directory(target_dir, max_depth=None)
        apply_imported_project(imported_project, import_mode, "フォルダから読み込み")

        st.session_state.settings["last_source_directory"] = target_dir
        save_settings(st.session_state.settings)
        st.sidebar.success(f"{import_mode}しました: {target_dir}")
        st.rerun()
    else:
        st.sidebar.error("フォルダパスが正しくありません。")

if st.sidebar.button(
    "PNGメタデータから読み込む",
    help="生成情報付きPNGから生成ソース（プロンプト）を復元します。",
    key="png_metadata_import",
):
    if os.path.isdir(target_dir):
        imported_project = Project(source_directory=target_dir)

        with st.spinner("PNGメタデータから生成ソース（プロンプト）を復元しています..."):
            import_summary = add_image_metadata_import(imported_project, target_dir)
            imported_project, line_summary = create_prompt_lines_from_latest_image_import(imported_project)
        apply_imported_project(imported_project, import_mode, "PNGメタデータを読み込み")

        st.session_state.settings["last_source_directory"] = target_dir
        save_settings(st.session_state.settings)

        no_metadata_count = max(import_summary.get("image_count", 0) - import_summary.get("metadata_count", 0), 0)
        st.sidebar.success(
            f"{import_mode}: {line_summary['created_count']}件 / "
            f"スキップ: {line_summary['skipped_count']}件 / "
            f"メタデータなし: {no_metadata_count}件"
        )
        if import_summary.get("warnings"):
            st.sidebar.warning(f"警告: {len(import_summary['warnings'])}件のPNGを確認してください。")
        if line_summary.get("path_warning_count"):
            st.sidebar.warning(f"読み込みフォルダ外の画像パスを検出しました: {line_summary['path_warning_count']}件")
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
    export_context = export_context_key(st.session_state.get("project"))
    computed_export_dir = default_prompt_image_export_dir(st.session_state.get("project"))
    saved_export_dir = st.session_state.settings.get("last_export_set_directory", "")
    saved_export_context = st.session_state.settings.get("last_export_set_context", "")
    default_set_export_dir = saved_export_dir if saved_export_dir and saved_export_context == export_context else computed_export_dir
    export_set_dir = st.text_input("出力先フォルダ", default_set_export_dir, key="export_prompt_image_set_dir")
    export_filename_prefix = st.text_input(
        "ファイル名プレフィックス",
        st.session_state.settings.get("last_export_filename_prefix", "illustration"),
        key="export_prompt_image_filename_prefix",
    )
    include_kind_label = st.checkbox(
        "reference/candidate等の種別名を付ける",
        value=st.session_state.settings.get("last_export_include_kind_label", True),
        key="export_prompt_image_include_kind_label",
    )
    st.markdown("##### 公開用安全化")
    st.caption("PNG画像には、生成環境やローカルフォルダ情報が含まれている場合があります。")
    st.caption("公開用イラスト集では、メタデータ削除を推奨します。")
    st.caption("公開用出力では、PNG内の生成情報や画像プロパティ情報をできるだけ削除します。")
    strip_metadata = st.checkbox(
        "PNGメタデータを削除（推奨）",
        value=st.session_state.settings.get("last_export_strip_metadata", True),
        key="export_prompt_image_strip_metadata",
    )
    include_prompt_metadata = st.checkbox(
        "生成ソース（プロンプト）をPNGに埋め込む",
        value=st.session_state.settings.get("last_export_include_prompt_metadata", False),
        key="export_prompt_image_include_prompt_metadata",
    )
    include_workflow_metadata = st.checkbox(
        "ComfyUI workflowを保持",
        value=st.session_state.settings.get("last_export_include_workflow_metadata", False),
        key="export_prompt_image_include_workflow_metadata",
    )
    include_environment_metadata = st.checkbox(
        "制作環境情報を保持",
        value=st.session_state.settings.get("last_export_include_environment_metadata", False),
        key="export_prompt_image_include_environment_metadata",
    )
    if st.button("イラスト・生成ソースセットを出力", key="export_prompt_image_set"):
        if st.session_state.project:
            summary = export_prompt_image_set(
                st.session_state.project,
                export_set_dir,
                disabled_modules=st.session_state.disabled_modules,
                filename_prefix=export_filename_prefix,
                include_kind_label=include_kind_label,
                strip_metadata=strip_metadata,
                include_prompt_metadata=include_prompt_metadata,
                include_workflow_metadata=include_workflow_metadata,
                include_environment_metadata=include_environment_metadata,
            )
            st.session_state.settings["last_export_set_directory"] = export_set_dir
            st.session_state.settings["last_export_set_context"] = export_context
            st.session_state.settings["last_export_filename_prefix"] = export_filename_prefix
            st.session_state.settings["last_export_include_kind_label"] = include_kind_label
            st.session_state.settings["last_export_strip_metadata"] = strip_metadata
            st.session_state.settings["last_export_include_prompt_metadata"] = include_prompt_metadata
            st.session_state.settings["last_export_include_workflow_metadata"] = include_workflow_metadata
            st.session_state.settings["last_export_include_environment_metadata"] = include_environment_metadata
            save_settings(st.session_state.settings)
            st.sidebar.success(
                f"出力成功: 生成ソース {summary['prompt_count']}件 / "
                f"画像 {summary['image_count']}件 -> {summary['output_dir']}"
            )
            if summary["metadata_stripped_count"]:
                st.sidebar.info(f"PNGメタデータを削除しました: {summary['metadata_stripped_count']}件")
            if summary["metadata_written_count"]:
                st.sidebar.info(f"PNGメタデータを書き込みました: {summary['metadata_written_count']}件")
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
st.sidebar.info("イラストを選んで生成ソース（プロンプト）の編集に入り、差分や続きのイラストを作成します。")
st.sidebar.markdown("- 生成ソース（プロンプト）の編集\n- 差分イラストを作る\n- このルートの次のイラストを作る\n- 候補イラストを生成する")
edition_label = "PRO" if st.session_state.edition == "PRO" else "FREE"
st.sidebar.write(f"**エディション:** {edition_label}")

scope_mode = "生成ソース（プロンプト）の編集" if st.session_state.get("focused_line_id") else "全体表示"
st.sidebar.write(f"**編集範囲:** {scope_mode}")

if st.session_state.get("focused_line_id") and st.session_state.project:
    line = next((l for l in st.session_state.project.prompt_lines if l.id == st.session_state.focused_line_id), None)
    if line:
        st.sidebar.caption(f"対象: {line.original_file_name}")
elif is_free():
    st.sidebar.info("イラスト一覧で対象を選び、生成ソース（プロンプト）の編集に入ってから差分作成・継続してください。")

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
        st.caption("Connect Modeは生成ソース（プロンプト）の編集中にのみ使用できます。選択した2つのノードをつなげる編集機能です。")
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
    st.title("プロジェクトを作成")
    st.info("サイドバーから新規プロジェクトを作成するか、保存済みプロジェクトを開いてください。")
    st.markdown("""
    **次にできること**
    - 新しいイラスト集プロジェクトを作成する。
    - 既存のプロンプトや画像がある場合はフォルダから読み込む。
    - 1枚のイラストを起点に、生成ソース（プロンプト）の編集で差分や続きを作る。
    """)
    st.stop()

if not st.session_state.project.prompt_lines:
    st.title("プロジェクトを作成しました")
    st.success("空の未保存プロジェクトです。既存イラスト集を読み込むか、このまま新規プロジェクトとして保存できます。")
    st.markdown("""
    **次の操作を選んでください**
    - 既存のプロンプトと画像をフォルダから読み込む。
    - 空のプロジェクト枠として先に保存する。
    - イラストが追加されたら、イラスト一覧で対象を選び、生成ソース（プロンプト）の編集・差分作成・継続・生成を行う。
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
if project:
    process_pending_focus_action()
    project = st.session_state.project

st.title("PromptGraph Lite")
st.caption("プロジェクト作成 -> 既存イラスト集の読み込み -> 生成ソース（プロンプト）の編集 -> 差分作成・継続 -> 保存・出力")

mode_cols = st.columns([1, 3])
with mode_cols[0]:
    if st.session_state.selection_mode_enabled:
        if st.button("通常表示に戻る", key="selection_mode_exit_top"):
            st.session_state.selection_mode_enabled = False
            st.rerun()
    else:
        if st.button("ギャラリー編集モード", type="primary", key="selection_mode_enter"):
            st.session_state.selection_mode_enabled = True
            st.session_state.focused_line_id = None
            st.session_state.selected_node_ids = []
            st.rerun()
with mode_cols[1]:
    st.caption("ギャラリー編集モードでは、画像を見ながら並び替え・削除候補選別・生成ソース編集・単発生成ができます。")

if st.session_state.selection_mode_enabled:
    render_illustration_selection_mode(project)
    st.stop()

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("グラフプレビュー")
    st.caption("イラスト集の元となっている生成ソース（プロンプト）の各ワードについて、作品中でどのようなワードが一緒に使われているかを確認することができます。")
    
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
        st.markdown("**⚡ 生成ソース（プロンプト）編集ヘルパー**")
        st.caption("Liteでは選択中の1イラスト編集が基本です。複数行や構造化された一括操作はPro版機能として制限されます。")

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
                    st.warning("⚠️ Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
                    use_global_word_ops = False
                else:
                    use_global_word_ops = True
                    st.info("⚠️ 生成ソース（プロンプト）の編集中ではありません。一致する単語をもとに**全イラスト**へ反映します。")
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
                                st.error("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
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
                    show_upgrade_dialog("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
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
                show_upgrade_dialog("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
                st.stop()
            if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                st.error("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
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
                    show_upgrade_dialog("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
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
                    show_upgrade_dialog("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
                    st.stop()
                if target_scope_key == "focused" and not st.session_state.get("focused_line_id") and st.session_state.edition == "FREE":
                    st.error("Lite版ではこの操作に生成ソース（プロンプト）の編集が必要です。イラスト一覧で対象を選び、編集画面に入ってから再試行してください。")
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
    line_section = st.container()
    node_section = st.container()

    with line_section:
        st.subheader("イラスト一覧")
        st.markdown("""
読み込んだイラスト集の各イラストを表示しています。

各イラストについて、生成ソース（プロンプト）を編集し、ComfyUIを通して再生成が可能です。

好きなイラストでストーリーを分岐させた差分イラスト集を作ることもできます。

各イラストの ↑ / ↓ で順番を調整可能です。
        """)
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
        selected_line_ids = [
            lid for lid, checked in st.session_state.selected_lines.items()
            if checked and any(line.id == lid and not getattr(line, "deleted", False) for line in display_lines)
        ]
        with c_del:
            if st.button("🗑️ 選択したイラストを削除", disabled=not selected_line_ids):
                deleted_count = delete_lines(selected_line_ids)
                if deleted_count:
                    st.session_state.branch_feedback = f"{deleted_count}件のイラストを削除しました。"
                st.rerun()
            st.caption("プロジェクト上の一覧から削除します。元画像ファイルは削除しません。")
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
                
            st.markdown(f"### 🎯 生成ソース（プロンプト）の編集: `{target_line.original_file_name}`")
            st.caption("このイラストの生成ソース（プロンプト）を編集し、差分作成、続きの作成、候補生成を行います。")
            if st.button("🔙 イラスト一覧に戻る"):
                st.session_state.focused_line_id = None
                st.rerun()

            st.markdown("#### 現在のイラスト")
            st.caption("元のイラストと出力対象イラストを並べて確認します。")
            img_c1, img_c2 = st.columns(2)
            with img_c1:
                st.caption("元のイラスト")
                reference_image_path = _existing_project_image_path(getattr(target_line, "image_path", None), project)
                if reference_image_path:
                    st.image(reference_image_path, width="stretch")
                else:
                    st.info("元のイラストはありません。")
                    show_missing_image_debug(getattr(target_line, "image_path", None), project)
            with img_c2:
                st.caption("出力対象イラスト")
                output_image_path = _existing_project_image_path(getattr(target_line, "generated_image_path", None), project)
                if output_image_path:
                    st.image(output_image_path, width="stretch")
                else:
                    st.info("出力対象イラストはまだ選択されていません。")
                    show_missing_image_debug(getattr(target_line, "generated_image_path", None), project)

            st.markdown("#### 生成ソース（プロンプト）")
            st.caption("中央のグラフやPromptCloudからワードを選択すると、このイラストの生成ソース内で該当語が強調表示されます。")

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

            edit_panel = st.expander("生成ソース（プロンプト）を直接編集", expanded=True)
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

            st.markdown("#### このイラストを複製して差分イラストを作る")
            st.caption("現在のイラストを起点に、差分イラスト集の新しい話や続きを作成します。")
            branch_col, continue_col = st.columns(2)
            with branch_col:
                if st.button("差分イラストで新しい話を始める", type="primary"):
                    request_focus_action("branch", target_line.id)
                    st.rerun()
            with continue_col:
                if st.button("差分イラストで続きを作る", type="primary"):
                    request_focus_action("continue", target_line.id)
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
                        autosave_current_project("候補イラストを生成")
                        st.success("候補イラストを1枚生成しました。出力対象イラストにする場合は明示的に選択してください。")
                        st.rerun()
                except Exception as e:
                    st.error(f"Liteの単体生成に失敗しました: {e}")

            render_lite_comfy_workflow_debug_preview(target_line)

            st.markdown("#### 候補イラスト管理")
            st.caption("候補を比較し、出力対象イラストまたは次の生成に使う元のイラストとして設定できます。")
            candidates = list(_get_line_generated_candidates(target_line))
            existing_candidates = []
            missing_candidates = []
            for candidate in candidates:
                candidate_path = _candidate_path(candidate)
                if not candidate_path:
                    continue
                resolved_candidate_path = _existing_project_image_path(candidate_path, project)
                if resolved_candidate_path:
                    existing_candidates.append((candidate, candidate_path, resolved_candidate_path))
                else:
                    missing_candidates.append(candidate)
            if missing_candidates:
                st.caption(f"保存済み候補パスのうち {len(missing_candidates)} 件が見つかりません。")

            if existing_candidates:
                with st.expander("候補イラスト", expanded=True):
                    candidate_items = list(reversed(existing_candidates))
                    for row_start in range(0, len(candidate_items), 2):
                        candidate_cols = st.columns(2)
                        for offset, candidate_col in enumerate(candidate_cols):
                            candidate_index = row_start + offset
                            if candidate_index >= len(candidate_items):
                                continue
                            _candidate, stored_candidate_path, resolved_candidate_path = candidate_items[candidate_index]
                            with candidate_col:
                                st.image(resolved_candidate_path, width="stretch")
                                st.caption(stored_candidate_path)
                                if st.button("出力対象イラストにする", key=f"after_{target_line.id}_{candidate_index}"):
                                    set_candidate_as_after(target_line, stored_candidate_path)
                                    st.success("出力対象イラストに設定しました。")
                                    st.rerun()
                                if st.button("元のイラストにする", key=f"ref_{target_line.id}_{candidate_index}"):
                                    set_candidate_as_reference(target_line, stored_candidate_path)
                                    st.success("元のイラストに設定しました。")
                                    st.rerun()
            else:
                st.info("候補イラストはまだありません。次のイラスト作成に進む前に候補を生成できます。")

            if st.button("🔙 イラスト一覧に戻る", key=f"focus_back_bottom_{target_line.id}"):
                st.session_state.focused_line_id = None
                st.rerun()
                
        else:
            visible_line_ids = [line.id for line in display_lines]
            for visible_index, l in enumerate(display_lines):
                title = f"[{l.original_file_name}] イラスト {l.original_index}"
                if l.edited:
                    title += "（編集済み）"
                if getattr(l, "continued_from", None):
                    title += "（続き）"
                elif l.duplicated_from:
                    title += "（差分）"
                    
                col_chk, col_thumb, col_exp = st.columns([0.05, 0.18, 0.77])
                with col_chk:
                    st.session_state.selected_lines[l.id] = st.checkbox("選択", value=st.session_state.selected_lines.get(l.id, False), key=f"chk_{l.id}", label_visibility="collapsed")

                with col_thumb:
                    thumbnail_path = get_line_thumbnail_path(l, project)
                    if thumbnail_path:
                        st.image(thumbnail_path, width=72)
                    else:
                        st.caption("画像なし")
                        show_missing_image_debug(getattr(l, "image_path", None), project)

                with col_exp:
                    with st.expander(title):
                        if st.button("🎯 編集 / 差分作成", key=f"focus_btn_{l.id}"):
                            st.session_state.focused_line_id = l.id
                            st.rerun()
                            
                        line_image_path = _existing_project_image_path(getattr(l, "image_path", None), project)
                        if line_image_path:
                            c_img, c_txt = st.columns([1, 2])
                            with c_img:
                                st.image(line_image_path, width="stretch")
                            with c_txt:
                                new_text = st.text_area("生成ソース", l.current_text, key=f"text_{l.id}", label_visibility="collapsed")
                        else:
                            show_missing_image_debug(getattr(l, "image_path", None), project)
                            new_text = st.text_area("生成ソース", l.current_text, key=f"text_{l.id}")
                            
                        if new_text != l.current_text:
                            if st.button("変更を保存", key=f"save_{l.id}"):
                                if is_free() and not st.session_state.get("focused_line_id"):
                                    st.error("Lite版では編集に生成ソース（プロンプト）の編集画面が必要です。編集画面に入ってから編集してください。")
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
                        if c3.button("差分作成", key=f"dup_{l.id}", help="このイラストの直後に差分イラストを作成します"):
                            request_focus_action("branch", l.id)
                            st.rerun()
                        if c4.button("削除", key=f"del_{l.id}", help="このイラストを削除"):
                            delete_line(l.id)
                            st.rerun()

    with node_section:
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
