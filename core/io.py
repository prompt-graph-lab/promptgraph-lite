import os
import glob
import json
from dataclasses import asdict
import dataclasses
from typing import List, Tuple
from core.project import Project, PromptLine, PromptNode
from core.parser import parse_prompt
from core.graph_builder import build_graph
import logging

logger = logging.getLogger(__name__)

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

# JSONのエンコード/デコードでSetなどを処理するカスタムEncoder
class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)

def save_project_to_json(project: Project, output_path: str):
    data = asdict(project)
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
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, cls=SetEncoder, indent=2, ensure_ascii=False)

def load_project_from_json(json_path: str) -> Project:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # dict から dataclass への復元
    project = Project(source_directory=data.get("source_directory", ""))
    
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
