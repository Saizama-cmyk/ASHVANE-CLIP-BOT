"""Bounded local ComfyUI Flux.2 illustrations; cancellation owns one prompt only."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from .util import ERR_SNIPPET

logger = logging.getLogger("clipbot.story_comfy")
FLUX_LATENT_STRIDE = 16


def image_reference(record: dict, expected_type: str) -> dict:
    """Never use a server-provided filesystem path or URL as a download target."""
    name = record.get("filename", record.get("name"))
    folder = record.get("subfolder", "")
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
            or name in (".", "..") or not isinstance(folder, str)
            or (folder and not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", folder))
            or record.get("type", expected_type) != expected_type):
        raise ValueError("ComfyUI returned an unsafe image reference")
    return {"filename": name, "subfolder": folder, "type": expected_type}


def decode_illustration(raw: bytes, max_pixels: int) -> Image.Image:
    """Decode a real single-frame image, not merely a successful HTTP response."""
    with Image.open(io.BytesIO(raw)) as source:
        if source.width * source.height > max_pixels or getattr(source, "n_frames", 1) != 1:
            raise ValueError("Generated illustration is oversized or animated")
        source.load()
        return ImageOps.exif_transpose(source).convert("RGB")


def flux_workflow(prompt: str, width: int, height: int, cfg, prefix: str,
                  reference: str = "") -> dict:
    """Core nodes verified in the installed ComfyUI; no custom-node installation."""
    graph = {
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": cfg.comfy_unet, "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": cfg.comfy_clip, "type": "flux2", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": cfg.comfy_vae}},
        "text": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "guidance": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["text", 0], "guidance": cfg.comfy_guidance}},
        "guider": {"class_type": "BasicGuider", "inputs": {"model": ["model", 0], "conditioning": ["guidance", 0]}},
        "latent": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "sigmas": {"class_type": "Flux2Scheduler", "inputs": {"steps": cfg.comfy_steps, "width": width, "height": height}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": cfg.comfy_seed}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sample": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0], "sigmas": ["sigmas", 0], "latent_image": ["latent", 0]}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": prefix}},
    }
    if reference:
        graph["reference_image"] = {"class_type": "LoadImage", "inputs": {"image": reference}}
        graph["reference_encode"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["reference_image", 0], "vae": ["vae", 0]}}
        graph["reference"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["guidance", 0], "latent": ["reference_encode", 0]}}
        graph["guider"]["inputs"]["conditioning"] = ["reference", 0]
    return graph


class ComfyStoryImages:
    """Caller supplies a URL validated by story_render.local_service_url."""
    def __init__(self, http, base: str, cfg):
        self.http, self.base, self.cfg = http, base.rstrip("/"), cfg
        self.limit = cfg.generated_media_max_mb * 1024 * 1024
        self.timeout = cfg.comfy_timeout_s

    async def _request(self, method: str, route: str, *, binary: bool = False, empty_ok: bool = False, **kwargs):
        limit = self.limit if binary else self.cfg.comfy_metadata_max_bytes
        async with self.http.stream(method, self.base + route, timeout=self.timeout,
                                    follow_redirects=False, **kwargs) as response:
            if response.is_redirect:
                raise ValueError("ComfyUI redirects are not allowed")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > limit:
                    raise ValueError("ComfyUI response exceeds the configured size limit")
                raw.extend(chunk)
            if response.status_code == 400 and route == "/prompt":
                # Core validation failures otherwise look like an offline engine.
                try:
                    rejected = json.loads(raw)
                    details = json.dumps({key: rejected.get(key) for key in ("error", "node_errors")})
                except (ValueError, AttributeError):
                    details = "Invalid workflow response"
                raise ValueError("ComfyUI rejected Hollow's workflow: " + details[-ERR_SNIPPET:])
            response.raise_for_status()
        if binary:
            return bytes(raw)
        if empty_ok and not raw:
            return {}
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("ComfyUI returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("ComfyUI returned invalid metadata")
        return result

    async def _cancel(self, prompt_id: str) -> None:
        # The installed core supports targeted interrupts. Never omit prompt_id:
        # an empty body would instead interrupt an unrelated active workflow.
        try:
            async with asyncio.timeout(self.cfg.comfy_cancel_timeout_s):
                await self._request("POST", "/queue", empty_ok=True, json={"delete": [prompt_id]})
                await self._request("POST", "/interrupt", empty_ok=True, json={"prompt_id": prompt_id})
        except (httpx.HTTPError, ValueError, TimeoutError):
            logger.exception("Could not confirm cancellation of Hollow image prompt %s", prompt_id)

    async def _upload_reference(self, path: Path) -> str:
        if path.stat().st_size > self.limit:
            raise ValueError("Story reference image exceeds the configured size limit")
        def prepare():
            image = decode_illustration(path.read_bytes(), self.cfg.illustration_max_pixels)
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            if stream.tell() > self.limit:
                raise ValueError("Story reference image exceeds the configured size limit")
            return stream.getvalue()
        raw = await asyncio.to_thread(prepare)
        name = uuid.uuid4().hex + ".png"
        result = await self._request("POST", "/upload/image", files={"image": (name, raw, "image/png")},
                                     data={"type": "input", "overwrite": "false", "subfolder": "Ashvane_Hollow"})
        ref = image_reference(result, "input")
        if ref["filename"] != name or ref["subfolder"] != "Ashvane_Hollow":
            raise ValueError("ComfyUI did not preserve the owned reference image name")
        return ref["subfolder"] + "/" + ref["filename"]

    async def generate(self, prompt: str, width: int, height: int, target: Path,
                       reference_path: Path | None = None) -> dict:
        prompt_id = str(uuid.uuid4())
        complete = False
        try:
            async with asyncio.timeout(self.cfg.comfy_timeout_s):
                reference = await self._upload_reference(reference_path) if reference_path else ""
                latent_width = (width + FLUX_LATENT_STRIDE - 1) // FLUX_LATENT_STRIDE * FLUX_LATENT_STRIDE
                latent_height = (height + FLUX_LATENT_STRIDE - 1) // FLUX_LATENT_STRIDE * FLUX_LATENT_STRIDE
                graph = flux_workflow(prompt, latent_width, latent_height, self.cfg, "Ashvane_Hollow/" + prompt_id, reference)
                result = await self._request("POST", "/prompt", json={"prompt": graph, "prompt_id": prompt_id, "client_id": "ashvane-hollow"})
                if result.get("prompt_id") != prompt_id or result.get("node_errors"):
                    raise ValueError("ComfyUI could not accept Hollow's workflow. Check installed model filenames and core nodes.")
                while True:
                    history = await self._request("GET", "/history/" + prompt_id)
                    entry = history.get(prompt_id)
                    if entry:
                        status = entry.get("status", {})
                        if status.get("status_str") == "error":
                            details = next((item[1].get("exception_message", "") for item in status.get("messages", [])
                                            if isinstance(item, list) and len(item) == 2 and item[0] == "execution_error" and isinstance(item[1], dict)), "")
                            raise ValueError("Hollow image generation failed: " + str(details)[-ERR_SNIPPET:])
                        images = entry.get("outputs", {}).get("save", {}).get("images", [])
                        if images:
                            ref = image_reference(images[0], "output")
                            if ref["subfolder"] != "Ashvane_Hollow" or not ref["filename"].startswith(prompt_id):
                                raise ValueError("ComfyUI returned an image from a different prompt")
                            raw = await self._request("GET", "/view", binary=True, params=ref)
                            def save():
                                image = decode_illustration(raw, self.cfg.illustration_max_pixels)
                                image = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)
                                target.parent.mkdir(parents=True, exist_ok=True)
                                temporary = target.with_suffix(".png.part")
                                try:
                                    image.save(temporary, format="PNG")
                                    temporary.replace(target)
                                finally:
                                    temporary.unlink(missing_ok=True)
                            await asyncio.to_thread(save)
                            complete = True
                            return {"provider": "comfyui", "prompt_id": prompt_id, "model": self.cfg.comfy_unet,
                                    "reference_used": bool(reference), "seed": self.cfg.comfy_seed}
                        if status.get("completed"):
                            raise ValueError("ComfyUI completed without returning Hollow's scene image")
                    await asyncio.sleep(self.cfg.comfy_poll_s)
        except httpx.HTTPError as exc:
            raise ValueError("Hollow ComfyUI is unavailable or rejected the workflow. Start its local server and verify the selected models.") from exc
        except TimeoutError as exc:
            raise ValueError("Hollow illustration exceeded its configured deadline") from exc
        finally:
            if not complete:
                await self._cancel(prompt_id)
