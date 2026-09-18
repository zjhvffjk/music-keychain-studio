import io
import json
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "workbench")]
from PIL import Image
import requests
import packaging_sources as sources
from packaging_comfy import ComfyClient
from packaging_service import PackagingService


def png():
    output = io.BytesIO()
    Image.new("RGB", (240, 240), (40, 110, 90)).save(output, "PNG")
    return output.getvalue()


class SourceTests(unittest.TestCase):
    def test_source_boundary(self):
        self.assertTrue(sources.allowed_cover("https://p1.music.126.net/abc.jpg"))
        for u in ["http://127.0.0.1/private", "https://music.126.net.evil.test/a", "file:///a", "https://user@p1.music.126.net/a"]:
            self.assertFalse(sources.allowed_cover(u), u)

    def test_image_validation(self):
        self.assertEqual(sources.clean_image(png()).size, (240, 240))
        with self.assertRaises(ValueError):
            sources.clean_image(b"not an image")

    def test_search_keeps_source_and_filters_bad_url(self):
        with patch.object(sources, "_get", return_value={"result": {"albums": [
            {"id": 1, "name": "Test", "picUrl": "https://p1.music.126.net/a", "artist": {"name": "Artist"}},
            {"id": 2, "name": "Bad", "picUrl": "http://localhost/private"}]}}):
            results, _ = sources.search_covers("Test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["sourceUrl"], "https://music.163.com/#/album?id=1")


class ComfyTests(unittest.TestCase):
    def test_remote_url_rejected(self):
        with self.assertRaises(ValueError):
            ComfyClient("http://external.example:8188")

    def test_missing_models_not_success(self):
        c = ComfyClient(workflow="/nonexistent-workflow.json")
        with patch.object(c, "get", side_effect=[{}, []]):
            self.assertFalse(c.readiness()["ready"])

    def test_builtin_references_cover(self):
        graph = ComfyClient.builtin("reference.png", "new visual", "sdxl.safetensors", 42)
        self.assertEqual(graph["2"]["inputs"]["image"], "reference.png")
        self.assertEqual(graph["7"]["inputs"]["latent_image"], ["4", 0])

    def test_ai_contract_returns_real_image(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cover.png"
            path.write_bytes(png())
            c = ComfyClient(workflow=str(Path(temp) / "missing.json"))
            upload, submit = Mock(), Mock()
            upload.json.return_value = {"name": "upload.png", "subfolder": "", "type": "input"}
            submit.status_code = 200
            submit.json.return_value = {"prompt_id": "abc"}
            output = Mock()
            output.__enter__ = Mock(return_value=output)
            output.__exit__ = Mock(return_value=False)
            output.iter_content.return_value = [png()]
            c.session = Mock()
            c.session.post.side_effect = [upload, submit]
            c.session.get.return_value = output
            with patch.object(c, "readiness", return_value={"ready": True, "checkpoint": "test"}), patch.object(c, "get", return_value={"abc": {"status": {"completed": True}, "outputs": {"9": {"images": [{"filename": "out.png", "type": "output", "subfolder": ""}]}}}}):
                image, info = c.generate(path, "new art", Mock())
            self.assertEqual(image.size, (240, 240))
            self.assertEqual(info["promptId"], "abc")
            self.assertTrue(c.session.post.call_args_list[1].args[0].endswith("/prompt"))

    def test_ai_execution_error_is_not_layout_fallback(self):
        c = ComfyClient(workflow="/missing.json")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cover.png"
            path.write_bytes(png())
            up, run = Mock(), Mock()
            up.json.return_value = {"name": "a.png"}
            run.status_code = 200
            run.json.return_value = {"prompt_id": "bad"}
            c.session = Mock()
            c.session.post.side_effect = [up, run]
            with patch.object(c, "readiness", return_value={"ready": True, "checkpoint": "test"}), patch.object(c, "get", return_value={"bad": {"status": {"status_str": "error"}}}):
                with self.assertRaisesRegex(ValueError, "生成失败"):
                    c.generate(path, "new art", Mock())


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = PackagingService(self.temp.name)
        self.candidate = self.service.register([{"album": "测试专辑", "artist": "测试歌手", "source": "用户上传", "sourceUrl": "", "coverSource": ""}])[0]
        (self.service.cache / (self.candidate["id"] + ".png")).write_bytes(png())

    def tearDown(self):
        self.temp.cleanup()

    def test_layout_persistence_and_archive(self):
        job = self.service.create({"coverId": self.candidate["id"], "mode": "layout"})
        for _ in range(1200):
            current = self.service.job(job["id"])
            if current["status"] != "running" and not self.service.active:
                break
            time.sleep(.05)
        self.assertEqual(current["status"], "done", current.get("error"))
        self.assertEqual(len(current["items"]), 10)
        restarted = PackagingService(self.temp.name)
        self.assertEqual(restarted.job(job["id"])["status"], "done")
        directory = Path(self.temp.name) / job["id"]
        with zipfile.ZipFile(directory / "专辑包装.zip") as archive:
            self.assertIn("mockup/album-packaging-presentation.png", archive.namelist())
            self.assertIn("print-ready/08-cut-fold-sheet-A4-300dpi.pdf", archive.namelist())
            self.assertIn("print-ready/09-cut-fold-sheet-A3-300dpi.pdf", archive.namelist())
            self.assertNotIn("task.json", archive.namelist())
            self.assertIn("Visual DNA", archive.read("使用说明.txt").decode())
        self.assertTrue((directory / "print-ready" / "08-cut-fold-sheet-A4-300dpi.png").is_file())
        self.assertTrue((directory / "print-ready" / "08-cut-fold-sheet-A4-300dpi.pdf").is_file())
        self.assertTrue((directory / "print-ready" / "09-cut-fold-sheet-A3-300dpi.png").is_file())
        self.assertTrue((directory / "print-ready" / "09-cut-fold-sheet-A3-300dpi.pdf").is_file())
        for item in current["items"]:
            with Image.open(directory / item["file"]) as im:
                self.assertEqual(im.size, (item["width"], item["height"]))
        with self.assertRaises(ValueError):
            self.service.asset(job["id"], "../task.json")

    def test_layout_asset_regeneration_updates_one_real_revision(self):
        job = self.service.create({"coverId": self.candidate["id"], "mode": "layout"})
        for _ in range(1200):
            current = self.service.job(job["id"])
            if current["status"] == "done" and not self.service.active:
                break
            time.sleep(.05)
        target = next(item for item in current["items"] if item["id"] == "poster")
        original = (Path(self.temp.name) / job["id"] / target["file"]).read_bytes()
        queued = self.service.mutate_asset(job["id"], "poster", "regenerate", "more evening light")
        self.assertEqual(next(item for item in queued["items"] if item["id"] == "poster")["status"], "regenerating")
        for _ in range(1200):
            current = self.service.job(job["id"])
            target = next(item for item in current["items"] if item["id"] == "poster")
            if target["status"] != "regenerating":
                break
            time.sleep(.05)
        self.assertEqual(target["status"], "draft", target.get("error"))
        self.assertEqual(target["revision"], 2)
        self.assertNotEqual(original, (Path(self.temp.name) / job["id"] / target["file"]).read_bytes())

    def test_restart_marks_interrupted(self):
        j = {"id": "abcdef1234567890", "status": "running"}
        self.service.save(j)
        restored = PackagingService(self.temp.name)
        self.assertEqual(restored.job(j["id"])["status"], "interrupted")

    def test_invalid_candidate_rejected(self):
        with self.assertRaises(ValueError):
            self.service.create({"coverId": "../../a", "mode": "layout"})

    def test_http_guards(self):
        import server
        httpd = server.Server(("127.0.0.1", 0), server.Handler)
        old = server.PACKAGING
        server.PACKAGING = self.service
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        session = requests.Session()
        session.trust_env = False
        base = f"http://127.0.0.1:{httpd.server_port}"
        try:
            self.assertEqual(session.get(base + "/packaging").status_code, 200)
            self.assertEqual(session.post(base + "/api/packaging/run", json={}, headers={"Origin": "http://evil.example"}).status_code, 403)
            self.assertEqual(session.post(base + "/api/packaging/run", json=[]).status_code, 400)
            self.assertEqual(session.get(base + "/api/packaging/jobs", headers={"Host": "evil.example"}).status_code, 403)
            self.assertEqual(session.get(base + "/api/packaging/jobs", headers={"Origin": "http://evil.example"}).status_code, 403)
            self.assertEqual(session.post(base + "/api/packaging/upload", data=png()).status_code, 200)
            self.assertEqual(session.get(base + "/api/packaging/jobs").json()["items"], [])
        finally:
            session.close()
            httpd.shutdown()
            httpd.server_close()
            server.PACKAGING = old


if __name__ == "__main__":
    unittest.main()
