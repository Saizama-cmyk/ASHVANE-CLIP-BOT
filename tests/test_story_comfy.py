"""Local ComfyUI workflow ownership, failure boundaries and real image handling."""
import asyncio
import io
import json
import re
from pathlib import Path

import httpx
from PIL import Image, ImageDraw
import pytest

from clipbot.config import Settings
from clipbot.story_comfy import ComfyStoryImages, decode_illustration, image_reference


def png():
    image = Image.new("RGB", (80, 40), "red")
    ImageDraw.Draw(image).rectangle((20, 0, 59, 39), fill="green")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class ComfyServer:
    def __init__(self, failure=""):
        self.requests, self.prompt_id, self.graph = [], "", None
        self.failure = failure
    async def __call__(self, request):
        body = await request.aread()
        path = request.url.path
        self.requests.append((path, body))
        if path == "/upload/image":
            name = re.search(rb'filename="([^"\r\n]+)"', body).group(1).decode()
            return httpx.Response(200, json={"name": name, "subfolder": "Ashvane_Hollow", "type": "input"})
        if path == "/prompt":
            data = json.loads(body)
            self.graph, self.prompt_id = data["prompt"], data["prompt_id"]
            if self.failure == "validation":
                return httpx.Response(400, json={"error": {"message": "Prompt validation failed"}, "node_errors": {"save": {"errors": [{"message": "Required input missing: codec"}]}}})
            return httpx.Response(200, json={"prompt_id": self.prompt_id, "node_errors": {}})
        if path.startswith("/history/"):
            if self.failure == "pending":
                return httpx.Response(200, json={})
            if self.failure == "error":
                return httpx.Response(200, json={self.prompt_id: {"status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "model missing"}]]}}})
            name = "../outside.png" if self.failure == "unsafe" else self.prompt_id + "_00001_.png"
            return httpx.Response(200, json={self.prompt_id: {"status": {"completed": True}, "outputs": {"save": {"images": [{"filename": name, "subfolder": "Ashvane_Hollow", "type": "output"}]}}}})
        if path == "/view":
            return httpx.Response(200, content=b"not an image" if self.failure == "invalid_image" else png())
        if path in ("/queue", "/interrupt"):
            return httpx.Response(200)
        raise AssertionError(path)


def test_real_image_is_cropped_without_stretch_and_no_global_requests(tmp_path):
    async def run():
        server = ComfyServer()
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
            result = await ComfyStoryImages(http, "http://127.0.0.1:8190", Settings().stories).generate("An original haunted kitchen", 32, 32, tmp_path / "scene.png")
        assert result["provider"] == "comfyui"
        assert result["reference_used"] is False
        with Image.open(tmp_path / "scene.png") as image:
            assert image.size == (32, 32)
            red, green, blue = image.getpixel((0, 16))
            assert red < 10 and green > 120 and blue == 0
        assert server.graph["clip"]["inputs"]["type"] == "flux2"
        assert server.graph["latent"]["inputs"]["width"] == 32
        assert not any(path in ("/queue", "/interrupt", "/free") for path, _ in server.requests)
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["error", "unsafe", "invalid_image"])
def test_failed_or_unsafe_generation_does_not_leave_a_scene_and_cancels_only_owned_job(tmp_path, failure):
    async def run():
        server = ComfyServer(failure)
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
            with pytest.raises((ValueError, OSError)):
                await ComfyStoryImages(http, "http://127.0.0.1:8190", Settings().stories).generate("A room", 32, 32, tmp_path / "scene.png")
        assert not (tmp_path / "scene.png").exists()
        cleanup = {path: json.loads(body) for path, body in server.requests if path in ("/queue", "/interrupt")}
        assert cleanup["/queue"] == {"delete": [server.prompt_id]}
        assert cleanup["/interrupt"] == {"prompt_id": server.prompt_id}
    asyncio.run(run())


def test_cancellation_while_queued_targets_the_owned_uuid_only(tmp_path):
    async def run():
        server = ComfyServer("pending")
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
            task = asyncio.create_task(ComfyStoryImages(http, "http://127.0.0.1:8190", Settings().stories).generate("A room", 32, 32, tmp_path / "scene.png"))
            while not server.prompt_id:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert json.loads(server.requests[-1][1]) == {"prompt_id": server.prompt_id}
        assert server.requests[-1][0] == "/interrupt"
    asyncio.run(run())


def test_reference_upload_uses_a_managed_name_and_core_reference_latent(tmp_path):
    async def run():
        source = tmp_path / "previous.png"
        source.write_bytes(png())
        server = ComfyServer()
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
            result = await ComfyStoryImages(http, "http://127.0.0.1:8190", Settings().stories).generate("Same person, new shot", 32, 32, tmp_path / "scene.png", source)
        assert result["reference_used"] is True
        assert server.graph["reference"]["class_type"] == "ReferenceLatent"
        assert server.graph["guider"]["inputs"]["conditioning"] == ["reference", 0]
        assert str(source) not in json.dumps(server.graph)
        assert server.graph["reference_image"]["inputs"]["image"].startswith("Ashvane_Hollow/")
    asyncio.run(run())


@pytest.mark.parametrize("record", [{"filename": "../x.png"}, {"filename": "C:\\x.png"}, {"filename": "x.png", "subfolder": "../out"}, {"filename": "x.png", "type": "input"}, {"filename": "x.png", "subfolder": "%2e%2e"}])
def test_server_image_paths_cannot_escape_the_fixed_view_route(record):
    with pytest.raises(ValueError, match="unsafe"):
        image_reference(record, "output")


def test_decoded_pixel_bound_is_enforced_before_resize():
    with pytest.raises(ValueError, match="oversized"):
        decode_illustration(png(), 100)


def test_workflow_validation_is_reported_instead_of_offline_service(tmp_path):
    async def run():
        server = ComfyServer("validation")
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
            with pytest.raises(ValueError, match="Required input missing: codec"):
                await ComfyStoryImages(http, "http://127.0.0.1:8190", Settings().stories).generate("A room", 32, 32, tmp_path / "scene.png")
        assert not (tmp_path / "scene.png").exists()
        assert json.loads(server.requests[-1][1]) == {"prompt_id": server.prompt_id}
    asyncio.run(run())


def test_metadata_and_image_download_size_are_bounded(tmp_path):
    async def run():
        cfg = Settings().stories.model_copy(update={"comfy_metadata_max_bytes": 10})
        server = ComfyServer()
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
            with pytest.raises(ValueError, match="size limit"):
                await ComfyStoryImages(http, "http://127.0.0.1:8190", cfg).generate("A room", 32, 32, tmp_path / "scene.png")
        assert not (tmp_path / "scene.png").exists()
    asyncio.run(run())
