"""Packaging HTTP feature, isolated from the existing song/print job runners."""
import json
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from packaging_comfy import ComfyClient
from packaging_render import NOTICE, presentation_from_assets, render, style_of
from packaging_sources import MAX_IMAGE, clean_image, fetch_cover, search_covers
from packaging_print import export_print_ready
from art_director import build as build_art_direction

ROOT = Path(__file__).resolve().parents[1]

COMPONENT_DIRECTIONS = {
    "back": "a cinematic reverse-side environment with generous quiet space for a future track list; no subject copied from the reference",
    "disc": "an abstract radial visual, material texture and circular movement, suitable for a CD face; no readable text",
    "booklet_cover": "an editorial alternate scene for a booklet cover, intimate but distinct from the album cover",
    "booklet_spread": "a wide two-page editorial environment with one side visually quieter for notes and lyrics",
    "lyrics": "a restrained paper-and-light still life with open calm space for lyric typography",
    "inner_sleeve": "a wide gatefold environment, a new location or perspective in the same visual world",
    "poster": "a vertical gallery poster scene with a strong focal point, cinematic light and ample type space",
    "postcard": "a small collectible postcard scene, a different close detail or distant view from the same world",
}


def component_prompt(key, style, edit=""):
    """Master art direction plus a distinct scene brief for every physical part."""
    master = ("Album packaging art direction. Create a completely new scene, not a crop, remake or near-copy of the reference. "
              "Keep only the visual DNA: palette " + ", ".join(style["palette"]) + "; mood " + style["mood"] +
              "; style " + style["style"] + ". Refined contemporary music-art editorial photography or illustration, "
              "natural material detail, cinematic lighting, no text, letters, logos, watermark, label, barcode or signature. ")
    return master + "Component brief: " + COMPONENT_DIRECTIONS[key] + (". Requested adjustment: " + edit if edit else "")


class PackagingService:
    def __init__(self, directory=None):
        self.directory = Path(directory or ROOT / "outputs" / "专辑包装")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cache = self.directory / "_covers"
        self.cache.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.candidates = {}
        self.jobs = {}
        self.active = None
        for path in self.directory.glob("*/task.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if not re.fullmatch(r"[a-f0-9]{16}", job["id"]) or path.parent.name != job["id"]:
                    continue
                if job["status"] == "running":
                    job.update(status="interrupted", phase="工作台已重启", error="生成中断。若使用 AI，请先检查 ComfyUI 队列再重试。")
                    self.save(job)
                self.jobs[job["id"]] = job
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def save(self, job):
        path = self.directory / job["id"] / "task.json"
        path.parent.mkdir(exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def public(self, job):
        return json.loads(json.dumps(job, ensure_ascii=False))

    def register(self, items):
        now = time.time()
        with self.lock:
            self.candidates = {k: v for k, v in self.candidates.items() if now - v["created"] < 86400}
            for candidate in items:
                candidate["id"] = uuid.uuid4().hex
                candidate["created"] = now
                self.candidates[candidate["id"]] = candidate
        return [{k: v for k, v in c.items() if k not in ("coverSource", "created")} for c in items]

    def candidate(self, cid):
        with self.lock:
            candidate = self.candidates.get(cid)
            if not candidate or time.time() - candidate["created"] > 86400:
                raise ValueError("封面选择已过期，请重新搜索或上传")
            return dict(candidate)

    def cover(self, cid):
        candidate = self.candidate(cid)
        target = self.cache / (cid + ".png")
        if not target.is_file():
            im = fetch_cover(candidate["coverSource"])
            tmp = target.with_name(cid + "-" + uuid.uuid4().hex + ".tmp")
            im.save(tmp, format="PNG")
            tmp.replace(target)
        return target

    def create(self, data):
        if not isinstance(data, dict):
            raise ValueError("请求格式错误")
        candidate = self.candidate(str(data.get("coverId", "")))
        mode = data.get("mode", "comfy")
        if mode not in ("comfy", "layout"):
            raise ValueError("请选择生成方式")
        if mode == "comfy":
            ready = ComfyClient().readiness()
            if not ready["ready"]:
                raise ValueError(ready["reason"])
        with self.lock:
            if self.active:
                raise ValueError("已有包装任务正在生成，请等待完成")
            jid = uuid.uuid4().hex[:16]
            job = {"id": jid, "title": str(data.get("album") or candidate["album"])[:160],
                   "artist": str(data.get("artist") or candidate["artist"])[:160], "mode": mode,
                   "status": "running", "phase": "准备封面", "done": 0, "total": 12,
                   "created": time.strftime("%Y-%m-%d %H:%M:%S"), "items": [], "error": None,
                   "source": {k: candidate.get(k, "") for k in ("album", "artist", "source", "sourceUrl", "coverSource", "albumId")},
                   "notice": NOTICE}
            if isinstance(data.get("artDirection"), dict):
                job["artDirection"] = data["artDirection"]
            self.jobs[jid] = job
            self.active = jid
            self.save(job)
            snapshot = self.public(job)
        threading.Thread(target=self.run, args=(job, candidate), daemon=True).start()
        return snapshot

    def run(self, job, candidate):
        directory = self.directory / job["id"]
        def update(phase, **extra):
            with self.lock:
                job.update(phase=phase, **extra)
                self.save(job)
        try:
            from PIL import Image
            cover = Image.open(self.cover(candidate["id"])).convert("RGB")
            cover.save(directory / "参考封面.png")
            style = style_of(cover)
            update("已提取封面色板与版式风格", style=style)
            artwork = None
            if job["mode"] == "comfy":
                artwork, generations = {}, {}
                ai_dir = directory / "AI场景"
                ai_dir.mkdir(exist_ok=True)
                for number, key in enumerate(COMPONENT_DIRECTIONS, 1):
                    update("AI 场景扩展：" + key, done=number, total=12)
                    image, info = ComfyClient().generate(directory / "参考封面.png", component_prompt(key, style), update)
                    image.save(ai_dir / (key + ".png"))
                    artwork[key], generations[key] = image, info
                update("9 个独立 AI 场景已完成，正在编排资产", generation=generations)
            items, mockup = render(directory, cover, artwork, job["title"], job["artist"], style, update, seed=int(job["id"][:6], 16))
            assets = {item["id"]: directory / item["file"] for item in items}
            update("正在生成 Print Ready 文件", done=11, total=12)
            print_ready = export_print_ready(directory, assets, job["title"], job["artist"], page_kind="a4")
            method = "ComfyUI 场景扩展 + 独立资产编排" if job["mode"] == "comfy" else "Visual DNA 衍生场景（无 AI 新场景）+ 独立资产编排"
            source = {"notice": NOTICE, "method": method, "source": job["source"], "style": style,
                      "parts": items, "generation": job.get("generation"), "created": job["created"]}
            (directory / "来源与设计说明.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
            (directory / "使用说明.txt").write_text(
                NOTICE + "\n" + method + "\n\n封面及艺人相关内容的权利归各自权利人所有。公开可访问不代表获得再利用授权。\n"
                "默认仅用于个人设计概念；不声称官方出版、授权或厂牌物料。\n"
                "歌词和曲目留白，未生成假歌词、假曲目或版权声明。\n"
                "本次是像素效果稿，不含印刷出血、刀模、色彩管理或尺寸校准。\n"
                "来源：" + job["source"]["source"] + "\n" + job["source"]["sourceUrl"], encoding="utf-8")
            pdf_files = ["print-ready/08-cut-fold-sheet-A4-300dpi.pdf", "print-ready/09-cut-fold-sheet-A3-300dpi.pdf"]
            files = [i["file"] for i in items] + [mockup["file"]] + [x["file"] for x in print_ready if x["kind"] == "print"] + pdf_files + ["参考封面.png", "来源与设计说明.json", "使用说明.txt", "print-ready/print-ready-manifest.json"]
            if job["mode"] == "comfy":
                files.extend("AI场景/" + key + ".png" for key in COMPONENT_DIRECTIONS)
            with zipfile.ZipFile(directory / "专辑包装.zip", "w", zipfile.ZIP_DEFLATED) as archive:
                for file in files:
                    archive.write(directory / file, file)
            update("生成完成", status="done", done=12, total=12, items=items, mockup=mockup, printReady=print_ready, method=method)
        except (Exception, SystemExit) as e:
            update("生成失败", status="error", error=str(e)[:350])
        finally:
            with self.lock:
                self.active = None

    def job(self, jid):
        with self.lock:
            if jid not in self.jobs:
                raise ValueError("未找到这条包装任务")
            return self.public(self.jobs[jid])

    def asset(self, jid, file):
        job = self.job(jid)
        allowed = {i["file"] for i in job["items"]}
        mockup_file = (job.get("mockup") or {}).get("file")
        if mockup_file:
            allowed.add(mockup_file)
        allowed.update(x.get("file", "") for x in job.get("printReady") or [])
        allowed.add("print-ready/print-ready-manifest.json")
        allowed.update(("print-ready/08-cut-fold-sheet-A4-300dpi.pdf", "print-ready/09-cut-fold-sheet-A3-300dpi.pdf"))
        allowed.update(("参考封面.png", "AI延展画面.png"))
        if file not in allowed:
            raise ValueError("文件不可访问")
        return self.directory / jid / file

    def _rebuild_deliverables(self, job):
        """Refresh the two dependent outputs after one flat asset changes."""
        directory = self.directory / job["id"]
        assets = {item["id"]: directory / item["file"] for item in job["items"]}
        job["mockup"] = presentation_from_assets(directory, {item["id"]: item["file"] for item in job["items"]}, job["title"], job["artist"])
        job["printReady"] = export_print_ready(directory, assets, job["title"], job["artist"], page_kind="a4")
        files = [item["file"] for item in job["items"]] + [job["mockup"]["file"]]
        files += [item["file"] for item in job["printReady"] if item["kind"] == "print"]
        files += ["print-ready/08-cut-fold-sheet-A4-300dpi.pdf", "print-ready/09-cut-fold-sheet-A3-300dpi.pdf",
                  "参考封面.png", "来源与设计说明.json", "使用说明.txt", "print-ready/print-ready-manifest.json"]
        if (directory / "AI延展画面.png").is_file():
            files.append("AI延展画面.png")
        with zipfile.ZipFile(directory / "专辑包装.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(directory / file, file)

    def _regenerate_asset(self, job_id, asset_id, revision, edit):
        """Generate a new scene revision, then update only the requested asset."""
        try:
            with self.lock:
                job = self.jobs[job_id]
                asset = next(item for item in job["items"] if item["id"] == asset_id)
            directory = self.directory / job_id
            from PIL import Image
            cover = Image.open(directory / "参考封面.png").convert("RGB")
            style = job["style"]
            artwork = None
            if job["mode"] == "comfy":
                artwork, _ = ComfyClient().generate(directory / "参考封面.png", component_prompt(asset_id, style, edit), lambda *_args, **_kw: None)
            revision_dir = directory / "_revisions" / (asset_id + "-r" + str(revision))
            revision_dir.mkdir(parents=True, exist_ok=True)
            regenerated, _ = render(revision_dir, cover, artwork, job["title"], job["artist"], style,
                                    lambda *_args, **_kw: None, seed=int(job_id[:6], 16) + revision * 1009)
            fresh = next(item for item in regenerated if item["id"] == asset_id)
            shutil.copy2(revision_dir / fresh["file"], directory / asset["file"])
            with self.lock:
                job = self.jobs[job_id]
                asset = next(item for item in job["items"] if item["id"] == asset_id)
                asset["revision"] = revision
                asset["status"] = "draft"
                asset.pop("error", None)
                self._rebuild_deliverables(job)
                self.save(job)
        except Exception as exc:
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    asset = next((item for item in job.get("items", []) if item["id"] == asset_id), None)
                    if asset:
                        asset["status"] = "regeneration-failed"
                        asset["error"] = str(exc)[:250]
                    self.save(job)

    def mutate_asset(self, jid, asset_id, action, edit=None):
        """Persist asset decisions and asynchronously create real new revisions."""
        with self.lock:
            job = self.jobs.get(jid)
            if not job or job.get("status") != "done":
                raise ValueError("只能编辑已完成的包装任务")
            asset = next((x for x in job.get("items", []) if x.get("id") == asset_id), None)
            if not asset:
                raise ValueError("未找到独立素材")
            if action == "lock":
                asset["locked"] = not bool(asset.get("locked"))
                asset["status"] = "locked" if asset["locked"] else "approved"
            elif action == "approve":
                asset["status"] = "approved"
            elif action == "edit":
                text = str(edit or "").strip()[:500]
                if not text:
                    raise ValueError("请输入编辑说明")
                asset["edit"] = text
                asset["status"] = "needs-regeneration"
            elif action == "regenerate":
                if asset.get("locked"):
                    raise ValueError("该素材已锁定；解锁后才可重新生成")
                revision = int(asset.get("revision", 1)) + 1
                asset["status"] = "regenerating"
                asset["edit"] = str(edit or asset.get("edit") or "")[:500]
                self.save(job)
                threading.Thread(target=self._regenerate_asset, args=(jid, asset_id, revision, asset["edit"]), daemon=True).start()
                return self.public(job)
            else:
                raise ValueError("不支持的素材操作")
            self.save(job)
            return self.public(job)

    def handle(self, handler, path, query, method):
        if not path.startswith("/api/packaging/"):
            return False
        def value(name, default=""):
            return (query.get(name) or [default])[0]
        try:
            if urlparse("http://" + handler.headers.get("Host", "")).hostname not in ("localhost", "127.0.0.1", "::1"):
                handler.close_connection = True
                handler._json({"error": "仅支持本机访问"}, 403)
                return True
            origin = handler.headers.get("Origin")
            if (origin and origin != "http://" + handler.headers.get("Host", "")) or handler.headers.get("Sec-Fetch-Site") == "cross-site":
                handler.close_connection = True
                handler._json({"error": "请从本机工作台发起操作"}, 403)
                return True
            if method == "POST":
                length = int(handler.headers.get("Content-Length", "0"))
                max_length = MAX_IMAGE if path.endswith("/upload") else 8192
                if not 0 < length <= max_length:
                    handler.close_connection = True
                    handler._json({"error": "请求为空或超过大小限制"}, 413)
                    return True
                raw = handler.rfile.read(length)
                if path == "/api/packaging/upload":
                    im = clean_image(raw)
                    candidate = {"album": "我的专辑", "artist": "", "source": "用户上传", "sourceUrl": "", "coverSource": "", "date": ""}
                    result = self.register([candidate])[0]
                    im.save(self.cache / (result["id"] + ".png"))
                    handler._json(result)
                elif path == "/api/packaging/run":
                    handler._json(self.create(json.loads(raw)), 202)
                elif path == "/api/packaging/asset-action":
                    data = json.loads(raw)
                    handler._json(self.mutate_asset(str(data.get("id", "")), str(data.get("assetId", "")), str(data.get("action", "")), data.get("edit")))
                else:
                    handler._json({"error": "接口不存在"}, 404)
                return True
            if path == "/api/packaging/status":
                handler._json(ComfyClient().readiness())
            elif path == "/api/packaging/search":
                rows, matched = search_covers(value("q"), value("kind", "album"), value("source", "all"))
                handler._json({"items": self.register(rows), "matchedArtist": matched})
            elif path == "/api/packaging/cover":
                handler._file(str(self.cover(value("id"))))
            elif path == "/api/packaging/style":
                from PIL import Image
                with Image.open(self.cover(value("id"))) as im:
                    style = style_of(im)
                candidate = self.candidate(value("id"))
                handler._json({**style, "artDirection": build_art_direction(candidate.get("album", ""), candidate.get("artist", ""), style)})
            elif path == "/api/packaging/jobs":
                with self.lock:
                    jobs = sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)[:60]
                    handler._json({"items": [self.public(j) for j in jobs]})
            elif path == "/api/packaging/state":
                handler._json(self.job(value("id")))
            elif path == "/api/packaging/asset":
                file = value("file")
                handler._file(str(self.asset(value("id"), file)), name=Path(file).name if value("dl") == "1" else None)
            elif path == "/api/packaging/zip":
                job = self.job(value("id"))
                if job["status"] != "done":
                    raise ValueError("任务尚未完成，暂不能下载")
                handler._file(str(self.directory / job["id"] / "专辑包装.zip"), name="专辑包装.zip")
            else:
                handler._json({"error": "接口不存在"}, 404)
        except (ValueError, KeyError, TypeError) as e:
            handler._json({"error": str(e)}, 400)
        except Exception:
            handler._json({"error": "处理失败，请稍后重试或查看本地服务状态"}, 500)
        return True


SERVICE = PackagingService()
