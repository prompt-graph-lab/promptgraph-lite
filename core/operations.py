from typing import List, Set
from core.project import Project
from core.graph_builder import build_graph
from core.parser import parse_prompt, extract_node_metadata, is_module_marker, is_structural_mod_marker
import re
import logging

logger = logging.getLogger(__name__)

def _rebuild_text(line):
    line.current_text = ", ".join(line.tokens)
    line.edited = True

def get_display_tokens(line) -> List[str]:
    from core.parser import extract_mod_info
    tokens = []
    for t in line.tokens:
        info = extract_mod_info(t)
        if info["type"] == "inline":
            if info["content"].strip():
                tokens.append(info["content"].strip())
            continue
        if info["type"] in ("open", "close"):
            continue
        tokens.append(t)
    return tokens

def get_display_tokens_from_text(text: str) -> List[str]:
    from core.parser import parse_prompt, extract_mod_info
    tokens = parse_prompt(text)
    result = []
    for t in tokens:
        info = extract_mod_info(t)
        if info["type"] == "inline":
            if info["content"].strip():
                result.append(info["content"].strip())
            continue
        if info["type"] in ("open", "close"):
            continue
        result.append(t)
    return result

def extract_module_structure_from_text(text: str) -> List[tuple]:
    from core.parser import parse_prompt, extract_mod_info
    tokens = parse_prompt(text)
    structure = []
    for t in tokens:
        info = extract_mod_info(t)
        if info["type"] == "inline":
            structure.append(("inline", info["name"]))
        elif info["type"] == "open":
            structure.append(("open", info["name"]))
        elif info["type"] == "close":
            structure.append(("close", info["name"]))
    return structure

def get_active_tokens(line, disabled_modules: set = None, fallback_prompt: str = None) -> List[str]:
    from core.parser import extract_mod_info
    if disabled_modules is None:
        disabled_modules = set()
    active = []
    mod_stack = []
    
    for t in line.tokens:
        info = extract_mod_info(t)
        
        if info["type"] == "inline":
            if info["name"] not in disabled_modules:
                if info["content"].strip():
                    active.append(info["content"].strip())
            continue
            
        if info["type"] == "open":
            mod_stack.append(info["name"])
            continue
        elif info["type"] == "close":
            mod_id = info["name"]
            if mod_id in mod_stack:
                # Find last occurrence of this mod_id and slice up to it
                idx = len(mod_stack) - 1 - mod_stack[::-1].index(mod_id)
                mod_stack = mod_stack[:idx]
            else:
                logger.warning(f"Malformed module marker: closing tag </mod:{mod_id}> found without matching opening tag in line {line.id}.")
            continue
            
        # Normal token
        if any(m in disabled_modules for m in mod_stack):
            continue
            
        active.append(t)
        
    if mod_stack:
        logger.warning(f"Malformed module marker: unclosed tags {mod_stack} at end of line {line.id}.")
        
    if not active and fallback_prompt:
        active = [fallback_prompt]
        
    return active

def get_available_modules(project: Project) -> List[str]:
    from core.parser import extract_mod_info
    modules = set()
    for line in project.prompt_lines:
        for t in line.tokens:
            info = extract_mod_info(t)
            if info["name"]:
                modules.add(info["name"])
    return sorted(list(modules))

def _is_match(token: str, target_base: str, match_mode: str) -> bool:
    if is_structural_mod_marker(token):
        return False
        
    meta = extract_node_metadata(token)
    base = meta["base_word"].lower()
    
    if match_mode == "exact":
        return base == target_base
    elif match_mode == "contains":
        # Token-aware / true substring matching
        return target_base in base
    return False

def _preserve_weight(new_word: str, original_token: str) -> str:
    orig_meta = extract_node_metadata(original_token)
    if orig_meta["weight"] == 1.0:
        return new_word
        
    new_meta = extract_node_metadata(new_word)
    if new_meta["weight"] != 1.0:
        return new_word # User already supplied new weight
        
    return f"({new_word}:{orig_meta['weight']})"

def count_matches(project: Project, target_word: str, target_line_ids: List[str] = None, match_mode: str = "exact") -> int:
    target_base = extract_node_metadata(target_word)["base_word"].lower()
    count = 0
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
        for t in line.tokens:
            if _is_match(t, target_base, match_mode):
                count += 1
    return count

def rename_word_global(project: Project, target_word: str, new_word: str, target_line_ids: List[str] = None, match_mode: str = "exact") -> Project:
    changed = False
    target_base = extract_node_metadata(target_word)["base_word"].lower()
    
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
        line_changed = False
        for i, t in enumerate(line.tokens):
            if _is_match(t, target_base, match_mode):
                line.tokens[i] = _preserve_weight(new_word, t)
                line_changed = True
                changed = True
        if line_changed:
            _rebuild_text(line)
    if changed:
        return build_graph(project)
    return project

def delete_word_global(project: Project, target_word: str, target_line_ids: List[str] = None, match_mode: str = "exact") -> Project:
    changed = False
    target_base = extract_node_metadata(target_word)["base_word"].lower()
    
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        original_len = len(line.tokens)
        line.tokens = [t for t in line.tokens if not _is_match(t, target_base, match_mode)]
        
        if len(line.tokens) != original_len:
            _rebuild_text(line)
            changed = True
            
    if changed:
        return build_graph(project)
    return project

def insert_word_global(project: Project, target_word: str, new_word: str, position: str = "after", target_line_ids: List[str] = None, match_mode: str = "exact") -> Project:
    changed = False
    target_base = extract_node_metadata(target_word)["base_word"].lower()
    
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        line_changed = False
        for t in line.tokens:
            if _is_match(t, target_base, match_mode):
                if position == "before":
                    new_tokens.append(new_word)
                    new_tokens.append(t)
                else:
                    new_tokens.append(t)
                    new_tokens.append(new_word)
                line_changed = True
                changed = True
            else:
                new_tokens.append(t)
                
        if line_changed:
            line.tokens = new_tokens
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def rename_node(project: Project, node_id: str, new_word: str, target_line_ids: List[str] = None) -> Project:
    changed = False
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        line_changed = False
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            if nid == node_id:
                line.tokens[idx] = new_word
                line.node_path[idx] = "__pending__"
                line_changed = True
                changed = True
                
        if line_changed:
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def delete_nodes(project: Project, node_ids: List[str], target_line_ids: List[str] = None) -> Project:
    changed = False
    node_set = set(node_ids)
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        new_node_path = []
        line_changed = False
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            if nid in node_set:
                line_changed = True
                changed = True
                continue
            new_tokens.append(token)
            new_node_path.append(nid)
            
        if line_changed:
            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def insert_node(project: Project, target_node_id: str, new_word: str, position: str = "after", target_line_ids: List[str] = None) -> Project:
    changed = False
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        new_node_path = []
        line_changed = False
        
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            if nid == target_node_id:
                if position == "before":
                    new_tokens.append(new_word)
                    new_node_path.append("__pending__")
                    new_tokens.append(token)
                    new_node_path.append(nid)
                else:
                    new_tokens.append(token)
                    new_node_path.append(nid)
                    new_tokens.append(new_word)
                    new_node_path.append("__pending__")
                line_changed = True
                changed = True
            else:
                new_tokens.append(token)
                new_node_path.append(nid)
                
        if line_changed:
            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def duplicate_nodes(project: Project, node_ids: List[str], target_line_ids: List[str] = None) -> Project:
    changed = False
    node_set = set(node_ids)
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        new_node_path = []
        line_changed = False
        
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            new_tokens.append(token)
            new_node_path.append(nid)
            if nid in node_set:
                new_tokens.append(token)
                new_node_path.append("__pending__")
                line_changed = True
                changed = True
                
        if line_changed:
            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def move_nodes(project: Project, node_ids: List[str], target_node_id: str, position: str = "after", target_line_ids: List[str] = None) -> Project:
    words_to_move = []
    for node_id in node_ids:
        if node_id in project.nodes:
            words_to_move.append(project.nodes[node_id].word)
            
    project = delete_nodes(project, node_ids, target_line_ids)
    
    if target_node_id in project.nodes:
        if position == "after":
            for w in reversed(words_to_move):
                project = insert_node(project, target_node_id, w, "after", target_line_ids)
        else:
            for w in words_to_move:
                project = insert_node(project, target_node_id, w, "before", target_line_ids)
                
    return project

def insert_subgraph(project: Project, target_node_id: str, words: List[str], position: str = "after", target_line_ids: List[str] = None) -> Project:
    changed = False
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        new_tokens = []
        new_node_path = []
        line_changed = False
        
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            if nid == target_node_id:
                if position == "before":
                    for w in words:
                        new_tokens.append(w)
                        new_node_path.append("__pending__")
                    new_tokens.append(token)
                    new_node_path.append(nid)
                else:
                    new_tokens.append(token)
                    new_node_path.append(nid)
                    for w in words:
                        new_tokens.append(w)
                        new_node_path.append("__pending__")
                line_changed = True
                changed = True
            else:
                new_tokens.append(token)
                new_node_path.append(nid)
                
        if line_changed:
            line.tokens = new_tokens
            line.node_path = new_node_path
            _rebuild_text(line)
            
    if changed:
        return build_graph(project)
    return project

def replace_with_subgraph(project: Project, target_node_ids: List[str], words: List[str], target_line_ids: List[str] = None) -> Project:
    changed = False
    target_set = set(target_node_ids)
    
    for line in project.prompt_lines:
        if line.deleted or (target_line_ids and line.id not in target_line_ids):
            continue
            
        line_targets = [nid for nid in line.node_path if nid in target_set]
        if not line_targets:
            continue
            
        first_target_idx = -1
        for idx, nid in enumerate(line.node_path):
            if nid in target_set:
                first_target_idx = idx
                break
                
        new_tokens = []
        new_node_path = []
        
        for idx, token in enumerate(line.tokens):
            nid = line.node_path[idx] if idx < len(line.node_path) else None
            
            if idx == first_target_idx:
                for w in words:
                    new_tokens.append(w)
                    new_node_path.append("__pending__")
                    
            if nid in target_set:
                continue
                
            new_tokens.append(token)
            new_node_path.append(nid)
            
        line.tokens = new_tokens
        line.node_path = new_node_path
        _rebuild_text(line)
        changed = True
            
    if changed:
        return build_graph(project)
    return project

def merge_duplicates_in_line(project: Project, line_id: str) -> Project:
    target_line = project.line_map.get(line_id)
    if not target_line or target_line.deleted:
        return project

    word_indices = {}
    for i, word in enumerate(target_line.tokens):
        word_lower = word.lower()
        if word_lower not in word_indices:
            word_indices[word_lower] = []
        word_indices[word_lower].append(i)

    indices_to_remove = set()
    for word_lower, indices in word_indices.items():
        if len(indices) <= 1:
            continue
        
        max_score = -1
        best_index = -1
        for idx in indices:
            node_id = target_line.node_path[idx] if idx < len(target_line.node_path) else None
            degree = 0
            freq = 0
            if node_id and node_id in project.nodes:
                node = project.nodes[node_id]
                degree = len(node.prev_node_ids) + len(node.next_node_ids)
                freq = node.count
                
            score = (degree * 10000) + (freq * 100) - idx
            if score > max_score:
                max_score = score
                best_index = idx
        
        for idx in indices:
            if idx != best_index:
                indices_to_remove.add(idx)
                
    if indices_to_remove:
        new_tokens = [t for i, t in enumerate(target_line.tokens) if i not in indices_to_remove]
        target_line.current_text = ", ".join(new_tokens)
        target_line.tokens = parse_prompt(target_line.current_text)
        target_line.edited = True
        return build_graph(project)
        
    return project

def merge_duplicates_all_lines(project: Project) -> Project:
    changed_any = False
    for target_line in project.prompt_lines:
        if target_line.deleted:
            continue
            
        word_indices = {}
        for i, word in enumerate(target_line.tokens):
            word_lower = word.lower()
            if word_lower not in word_indices:
                word_indices[word_lower] = []
            word_indices[word_lower].append(i)

        indices_to_remove = set()
        for word_lower, indices in word_indices.items():
            if len(indices) <= 1:
                continue
            
            max_score = -1
            best_index = -1
            for idx in indices:
                node_id = target_line.node_path[idx] if idx < len(target_line.node_path) else None
                degree = 0
                freq = 0
                if node_id and node_id in project.nodes:
                    node = project.nodes[node_id]
                    degree = len(node.prev_node_ids) + len(node.next_node_ids)
                    freq = node.count
                    
                score = (degree * 10000) + (freq * 100) - idx
                if score > max_score:
                    max_score = score
                    best_index = idx
            
            for idx in indices:
                if idx != best_index:
                    indices_to_remove.add(idx)
                    
        if indices_to_remove:
            new_tokens = [t for i, t in enumerate(target_line.tokens) if i not in indices_to_remove]
            target_line.current_text = ", ".join(new_tokens)
            target_line.tokens = parse_prompt(target_line.current_text)
            target_line.edited = True
            changed_any = True
            
    if changed_any:
        return build_graph(project)
    return project

def apply_node_weight(project: Project, node_ids: list[str], weight: float, target_line_ids: list[str] = None) -> Project:
    from core.parser import parse_prompt
        
    target_words = []
    for nid in node_ids:
        if nid in project.nodes:
            target_words.append(get_base_word(project.nodes[nid].word).lower())
            
    if not target_words:
        return project
        
    changed_any = False
    for line in project.prompt_lines:
        if line.deleted:
            continue
        if target_line_ids and line.id not in target_line_ids:
            continue
            
        new_tokens = []
        line_changed = False
        for token in line.tokens:
            base = get_base_word(token)
            if base.lower() in target_words:
                if weight == 1.0:
                    new_token = base
                else:
                    # Remove multiple spaces if any
                    new_token = f"({base}:{weight:.1f})"
                if new_token != token:
                    new_tokens.append(new_token)
                    line_changed = True
                else:
                    new_tokens.append(token)
            else:
                new_tokens.append(token)
                
        if line_changed:
            line.current_text = ", ".join(new_tokens)
            line.tokens = parse_prompt(line.current_text)
            line.edited = True
            changed_any = True
            
    if changed_any:
        return build_graph(project)
    return project
