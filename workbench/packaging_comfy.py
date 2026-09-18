"""Small local ComfyUI adapter. No cloud keys, no automatic model downloads."""
import copy
import json
import os
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from packaging_sources import clean_image

ROOT = Path(__file__).resolve().parents[1]


class ComfyClient:
    def __init__(self, url=None, workflow=None):
        self.url = (url or os.getenv("MINUET_COMFY_URL", "http://127.0.0.1:8188")).rstrip("/")
        u = urlparse(self.url)
        if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1") or u.username or u.password or u.query or u.fragment:
            raise ValueError("ComfyUI 地址必须是本机 HTTP 地址")
        self.workflow = Path(workflow or os.getenv("MINUET_COMFY_WORKFLOW", str(ROOT / "config" / "packaging_workflow.json")))
        self.session = requests.Session()
        self.session.trust_env = False

    def get(self, path, **kw):
        r = self.session.get(self.url + path, timeout=(3, 15), **kw)
        r.raise_for_status()
        return r.json()

    def template(self):
        if not self.workflow.is_file():
            return None
        data = json.loads(self.workflow.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not data or "nodes" in data:
            raise ValueError("请配置 ComfyUI 的 API 格式工作流，而非界面格式")
        if any(not isinstance(n, dict) or not isinstance(n.get("class_type"), str)
               or not isinstance(n.get("inputs"), dict) for n in data.values()):
            raise ValueError("图片工作流节点格式不完整")
        encoded = json.dumps(data)
        if "{{cover}}" not in encoded or "{{prompt}}" not in encoded:
            raise ValueError("图片工作流须包含 {{cover}} 和 {{prompt}} 占位符")
        if not any(n.get("class_type") == "SaveImage" for n in data.values() if isinstance(n, dict)):
            raise ValueError("图片工作流须包含 SaveImage 输出节点")
        return data

    def readiness(self):
        try:
            self.get("/system_stats")
            graph = self.template()
            if graph:
                info = self.get("/object_info")
                missing = sorted({n.get("class_type", "") for n in graph.values()} - set(info))
                if missing:
                    return {"connected": True, "ready": False, "reason": "工作流缺少节点：" + ", ".join(missing)}
                for node in graph.values():
                    definition = info[node["class_type"]].get("input", {})
                    fields = {**definition.get("required", {}), **definition.get("optional", {})}
                    for key, val in node.get("inputs", {}).items():
                        spec = fields.get(key, [])
                        if spec and isinstance(spec[0], list) and isinstance(val, str) and "{{" not in val and val not in spec[0]:
                            return {"connected": True, "ready": False, "reason": "工作流中的模型或选项不可用：" + key + " = " + val[:100]}
                return {"connected": True, "ready": True, "reason": "本地图片工作流已配置", "workflow": "custom"}
            checkpoints = self.get("/models/checkpoints")
            if not checkpoints:
                return {"connected": True, "ready": False, "reason": "ComfyUI 已连接，但还缺少可用的图片模型或生成流程。当前可使用封面衍生排版。"}
            chosen = os.getenv("MINUET_COMFY_CHECKPOINT", "")
            if not chosen:
                return {"connected": True, "ready": False, "reason": "请用 MINUET_COMFY_CHECKPOINT 指定兼容的 SD 1.5 / SDXL 图片模型，或配置图片工作流。"}
            if chosen not in checkpoints:
                return {"connected": True, "ready": False, "reason": "配置的图片模型未安装"}
            return {"connected": True, "ready": True, "reason": "本地图片模型已就绪", "checkpoint": chosen}
        except (requests.RequestException, ValueError, OSError, TypeError) as e:
            return {"connected": False, "ready": False, "reason": "无法使用本地 ComfyUI：" + (str(e)[:180] if not isinstance(e, requests.RequestException) else "请启动 ComfyUI 并检查本机地址")}

    @staticmethod
    def builtin(cover, prompt, checkpoint, seed):
        return {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "2": {"class_type": "LoadImage", "inputs": {"image": cover}},
            "3": {"class_type": "ImageScale", "inputs": {"image": ["2", 0], "upscale_method": "lanczos", "width": 768, "height": 768, "crop": "center"}},
            "4": {"class_type": "VAEEncode", "inputs": {"pixels": ["3", 0], "vae": ["1", 2]}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "text, logo, watermark, fake signature, barcode, blurry, low quality", "clip": ["1", 1]}},
            "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["4", 0], "seed": seed, "steps": 24, "cfg": 6, "sampler_name": "euler", "scheduler": "normal", "denoise": 0.7}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "Minuet/packaging"}},
        }

    def generate(self, cover_path, prompt, update, timeout=900):
        ready = self.readiness()
        if not ready["ready"]:
            raise ValueError(ready["reason"])
        seed = secrets.randbelow(2 ** 32)
        with open(cover_path, "rb") as f:
            r = self.session.post(self.url + "/upload/image", files={"image": ("minuet-" + uuid.uuid4().hex + ".png", f, "image/png")}, data={"type": "input", "overwrite": "false"}, timeout=(5, 60))
        r.raise_for_status()
        uploaded = r.json()
        cover = "/".join(x for x in (uploaded.get("subfolder", ""), uploaded["name"]) if x)
        template = self.template()
        def replace(v):
            if isinstance(v, dict):
                return {k: replace(x) for k, x in v.items()}
            if isinstance(v, list):
                return [replace(x) for x in v]
            if v == "{{seed}}":
                return seed
            if isinstance(v, str):
                return v.replace("{{cover}}", cover).replace("{{prompt}}", prompt)
            return v
        graph = replace(copy.deepcopy(template)) if template else self.builtin(cover, prompt, ready["checkpoint"], seed)
        r = self.session.post(self.url + "/prompt", json={"prompt": graph, "client_id": "minuet-" + uuid.uuid4().hex}, timeout=(5, 30))
        if r.status_code != 200:
            raise ValueError("ComfyUI 拒绝工作流，请检查节点及图片模型是否齐全")
        pid = r.json().get("prompt_id")
        if not pid:
            raise ValueError("ComfyUI 未返回任务编号")
        update("AI 已排队，等待本地画图", promptId=pid, seed=seed)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = self.get("/history/" + pid).get(pid)
            if history:
                status = history.get("status") or {}
                if status.get("status_str") == "error":
                    raise ValueError("本地 AI 生成失败，请在 ComfyUI 查看模型或显存错误")
                for node in (history.get("outputs") or {}).values():
                    for image in node.get("images", []):
                        if image.get("type") != "output":
                            continue
                        with self.session.get(self.url + "/view", params={k: image[k] for k in ("filename", "subfolder", "type") if k in image}, timeout=(5, 60), stream=True) as result:
                            result.raise_for_status()
                            raw = bytearray()
                            for chunk in result.iter_content(65536):
                                raw.extend(chunk)
                                if len(raw) > 16 * 1024 * 1024:
                                    raise ValueError("AI 图片超过 16 MB")
                        return clean_image(raw), {"promptId": pid, "seed": seed}
                if status.get("completed"):
                    raise ValueError("工作流完成但没有输出图片，请使用 SaveImage 节点")
            time.sleep(2)
        # Do not interrupt the shared queue or automatically resubmit an expensive job.
        raise ValueError("等待 AI 超时；原任务可能仍在 ComfyUI 中运行，请查看队列后再决定是否重试")
