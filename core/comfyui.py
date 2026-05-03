import json
import urllib.request
import urllib.parse
import urllib.error
import time
import os
import uuid
import websocket
import random
import logging

logger = logging.getLogger(__name__)

def build_prompt_by_group(project, prompt_line, disabled_modules=None):
    if disabled_modules is None:
        disabled_modules = set()
        
    grouped = {}
    mod_stack = []
    
    for idx, node_id in enumerate(prompt_line.node_path):
        token = prompt_line.tokens[idx] if idx < len(prompt_line.tokens) else ""
        
        if token.startswith("<mod:"):
            mod_stack.append(token[5:-1])
            continue
        elif token.startswith("</mod:"):
            mod_id = token[6:-1]
            if mod_id in mod_stack:
                i = len(mod_stack) - 1 - mod_stack[::-1].index(mod_id)
                mod_stack = mod_stack[:i]
            else:
                logger.warning(f"Malformed module marker: closing tag </mod:{mod_id}> found without matching opening tag in line {prompt_line.id}.")
            continue
            
        if any(m in disabled_modules for m in mod_stack):
            continue
            
        if node_id in project.nodes:
            node = project.nodes[node_id]
            group = getattr(node, "group", "default")
            val = getattr(node, "original", node.word)
            if group not in grouped:
                grouped[group] = []
            grouped[group].append(val)
            
    if mod_stack:
        logger.warning(f"Malformed module marker: unclosed tags {mod_stack} at end of line {prompt_line.id}.")
        
    return grouped

def inject_prompt_to_workflow(workflow_json, grouped_prompt, mapping, fallback_prompt=None):
    group_map = mapping.get("group_map", {})
    group_order = mapping.get("group_order")
    merge_mode = mapping.get("merge_mode", "merge")
    
    if group_order:
        ordered_groups = [(g, grouped_prompt[g]) for g in group_order if g in grouped_prompt]
        ordered_groups += [(g, grouped_prompt[g]) for g in grouped_prompt if g not in group_order]
    else:
        ordered_groups = list(grouped_prompt.items())
    
    dest_texts = {}
    for group, tokens in ordered_groups:
        if group not in group_map:
            logger.info(f"Unmapped group '{group}' -> defaulting to positive")
            dest_key = "positive"
        else:
            dest_key = group_map.get(group, "positive")
            
        if dest_key not in mapping:
            continue
            
        if dest_key not in dest_texts:
            dest_texts[dest_key] = []
        dest_texts[dest_key].extend(tokens)
        
    # Ensure all mapped targets exist even if empty
    for k in mapping.keys():
        if k not in ["group_map", "group_order", "merge_mode"] and k not in dest_texts:
            dest_texts[k] = []
            
    if fallback_prompt and "positive" in dest_texts and not dest_texts["positive"]:
        dest_texts["positive"] = [fallback_prompt]
        
    for dest_key, tokens in dest_texts.items():
            
        dest_config = mapping.get(dest_key)
        if not dest_config:
            continue
        
        node_id = str(dest_config.get("node_id"))
        input_key = dest_config.get("input_key")
        
        try:
            # Handle both raw API format and {"nodes": ...} format
            target_nodes = workflow_json.get("nodes", workflow_json) if isinstance(workflow_json, dict) else workflow_json
            
            if node_id not in target_nodes:
                logger.warning(f"Node {node_id} not found in workflow")
                continue
                
            inputs = target_nodes[node_id].get("inputs", {})
            if input_key not in inputs:
                logger.warning(f"input_key '{input_key}' not found in node {node_id}")
                continue
            
            tokens = list(dict.fromkeys(tokens))
            
            existing = target_nodes[node_id]["inputs"].get(input_key, "")
            if isinstance(existing, str):
                existing = existing.strip().rstrip(",")
            
            if merge_mode == "overwrite":
                merged = ", ".join(tokens)
            else:
                existing_tokens = [t.strip() for t in existing.split(",") if t.strip()] if isinstance(existing, str) else []
                for t in tokens:
                    if t not in existing_tokens:
                        existing_tokens.append(t)
                merged = ", ".join(existing_tokens)
            
            target_nodes[node_id]["inputs"][input_key] = merged
        except Exception as e:
            logger.warning(f"Failed to inject prompt to node {node_id}: {e}")
            pass
            
    return workflow_json

def generate_image_with_progress(workflow_json: dict, server_address: str, output_dir: str, file_prefix: str, timeout: int = 300):
    """
    ComfyUIにプロンプトを投げ、WebSocketで進捗を監視するジェネレータ関数。
    進捗中は {"type": "...", "text": "...", "value": float} の辞書をyieldする。
    完了時に保存された画像のパスを返す（ジェネレータの戻り値、または最終yieldの特別な形式で）。
    """
    server_address = server_address.replace("http://", "").replace("https://", "").strip("/")
    client_id = str(uuid.uuid4())
    
    # シード値をランダム化してComfyUIのキャッシュを回避する
    for node_id, node_data in workflow_json.items():
        if "inputs" in node_data:
            inputs = node_data["inputs"]
            for seed_key in ["seed", "noise_seed"]:
                if seed_key in inputs and isinstance(inputs[seed_key], (int, float)):
                    # 一般的な最大値 (2^64 - 1) までの範囲で乱数を生成
                    inputs[seed_key] = random.randint(0, 0xffffffffffffffff)
                    
    p = {"prompt": workflow_json, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data)
    
    yield {"type": "status", "text": "Connecting to ComfyUI...", "value": 0.0}
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read())
            prompt_id = result.get("prompt_id")
    except urllib.error.URLError as e:
        raise Exception(f"Failed to connect to ComfyUI at {server_address}. Is it running? Error: {e}")

    if not prompt_id:
        raise Exception("Failed to get prompt_id from ComfyUI.")

    yield {"type": "status", "text": "Prompt queued. Waiting for execution...", "value": 0.0}

    ws = websocket.WebSocket()
    try:
        ws.connect(f"ws://{server_address}/ws?clientId={client_id}")
        ws.settimeout(1.0)
    except Exception as e:
        raise Exception(f"Failed to connect to ComfyUI WebSocket: {e}")
        
    image_info = None
    start_time = time.time()
    
    while True:
        if time.time() - start_time > timeout:
            ws.close()
            raise Exception(f"ComfyUI execution timeout ({timeout}s exceeded)")
            
        try:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                msg_type = message.get("type")
                data = message.get("data", {})
                
                if msg_type == "execution_start":
                    yield {"type": "status", "text": "Execution started", "value": 0.05}
                elif msg_type == "executing":
                    node = data.get("node")
                    if node is None and data.get("prompt_id") == prompt_id:
                        # 完了
                        break
                elif msg_type == "progress":
                    value = data.get("value", 0)
                    max_val = data.get("max", 1)
                    if max_val > 0:
                        progress = value / max_val
                        # 10% ~ 90% の範囲にスケーリング
                        scaled_progress = 0.1 + (progress * 0.8)
                        yield {"type": "progress", "text": f"Sampling... {value}/{max_val}", "value": scaled_progress}
                elif msg_type == "execution_success" and data.get("prompt_id") == prompt_id:
                    break
                elif msg_type == "execution_error":
                    error_msg = data.get("exception_message", "Unknown error")
                    node_id = data.get("node_id", "")
                    node_type = data.get("node_type", "")
                    raise Exception(f"ComfyUI Execution Error in node {node_id} ({node_type}): {error_msg}")
        except websocket.WebSocketTimeoutException:
            continue
        except Exception as e:
            # タイムアウト等の場合はループを抜けるかエラーにする
            raise Exception(f"WebSocket error or execution failed: {e}")
            
    ws.close()
    
    yield {"type": "status", "text": "Execution done. Fetching image...", "value": 0.95}
    
    try:
        with urllib.request.urlopen(f"http://{server_address}/history/{prompt_id}") as response:
            history = json.loads(response.read())
    except Exception as e:
        raise Exception(f"Failed to get history: {e}")
        
    outputs = history.get(prompt_id, {}).get("outputs", {})
    for node_id, node_output in outputs.items():
        if "images" in node_output and len(node_output["images"]) > 0:
            image_info = node_output["images"][0]
            break
            
    if not image_info:
        raise Exception("No image was output by the workflow. Make sure there is a SaveImage node.")
        
    filename = image_info["filename"]
    subfolder = image_info.get("subfolder", "")
    folder_type = image_info.get("type", "output")
    
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    
    image_url = f"http://{server_address}/view?{url_values}"
    
    os.makedirs(output_dir, exist_ok=True)
    save_path = os.path.join(output_dir, f"{file_prefix}_{filename}")
    
    try:
        with urllib.request.urlopen(image_url) as response:
            image_data = response.read()
            with open(save_path, "wb") as f:
                f.write(image_data)
        
        yield {"type": "done", "text": "Completed!", "value": 1.0, "path": save_path}
    except Exception as e:
        raise Exception(f"Failed to download image: {e}")
