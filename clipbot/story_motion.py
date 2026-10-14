"""Owned local Wan image-to-video jobs; narration and delivery stay in the renderer."""
from __future__ import annotations

import asyncio
import math
import uuid
from pathlib import Path

import httpx

from .story_comfy import ComfyStoryImages, image_reference

WAN_SPATIAL_STRIDE = 32
WAN_TEMPORAL_STRIDE = 4
WAN_SEED_SPACE = 18446744073709551616
MP4_TYPE_START = 4
MP4_TYPE_END = 8


def motion_geometry(width, height, seconds, cfg):
    scale = cfg.wan_short_edge / min(width, height)
    w = max(WAN_SPATIAL_STRIDE, round(width * scale / WAN_SPATIAL_STRIDE) * WAN_SPATIAL_STRIDE)
    h = max(WAN_SPATIAL_STRIDE, round(height * scale / WAN_SPATIAL_STRIDE) * WAN_SPATIAL_STRIDE)
    frames = 1 + WAN_TEMPORAL_STRIDE * math.ceil(max(1, seconds * cfg.fps - 1) / WAN_TEMPORAL_STRIDE)
    limit = 1 + WAN_TEMPORAL_STRIDE * ((cfg.wan_max_frames - 1) // WAN_TEMPORAL_STRIDE)
    return w, h, min(limit, frames)


def wan_workflow(prompt, reference, width, height, frames, cfg, prefix, seed):
    return {
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": cfg.wan_unet, "weight_dtype": "default"}},
        "sampling": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["model", 0], "shift": cfg.wan_shift}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": cfg.wan_clip, "type": "wan", "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": cfg.wan_vae}},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": cfg.wan_negative_prompt}},
        "image": {"class_type": "LoadImage", "inputs": {"image": reference}},
        "latent": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"vae": ["vae", 0], "width": width, "height": height, "length": frames, "batch_size": 1, "start_image": ["image", 0]}},
        "sample": {"class_type": "KSampler", "inputs": {"model": ["sampling", 0], "positive": ["positive", 0], "negative": ["negative", 0], "latent_image": ["latent", 0], "seed": seed, "steps": cfg.wan_steps, "cfg": cfg.wan_guidance, "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "video": {"class_type": "CreateVideo", "inputs": {"images": ["decode", 0], "fps": cfg.fps}},
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0], "filename_prefix": prefix, "format": "mp4", "format.codec": "h264", "format.codec.encoding": "re-encode", "format.codec.encoding.crf": cfg.crf}},
    }


class ComfyStoryMotion(ComfyStoryImages):
    def __init__(self, http, base, cfg):
        super().__init__(http, base, cfg)
        self.timeout = cfg.wan_timeout_s

    async def generate_motion(self, prompt: str, reference_path: Path, width: int, height: int,
                              seconds: float, target: Path, *, seed: int) -> dict:
        prompt_id, complete = str(uuid.uuid4()), False
        temporary = target.with_suffix(".mp4.part")
        try:
            async with asyncio.timeout(self.timeout):
                reference = await self._upload_reference(reference_path)
                w, h, frames = motion_geometry(width, height, seconds, self.cfg)
                graph = wan_workflow(prompt, reference, w, h, frames, self.cfg, "Ashvane_Hollow/" + prompt_id, seed)
                response = await self._request("POST", "/prompt", json={"prompt": graph, "prompt_id": prompt_id, "client_id": "ashvane-hollow"})
                if response.get("prompt_id") != prompt_id or response.get("node_errors"):
                    raise ValueError("ComfyUI rejected Hollow's video workflow. Check its Wan models and core nodes.")
                while True:
                    history = await self._request("GET", "/history/" + prompt_id)
                    entry = history.get(prompt_id)
                    if entry:
                        status = entry.get("status", {})
                        if status.get("status_str") == "error":
                            raise ValueError("Hollow motion generation failed; inspect its local ComfyUI log.")
                        files = entry.get("outputs", {}).get("save", {}).get("images", [])
                        if files:
                            ref = image_reference(files[0], "output")
                            if (ref["subfolder"] != "Ashvane_Hollow" or not ref["filename"].startswith(prompt_id)
                                    or not ref["filename"].endswith(".mp4")):
                                raise ValueError("ComfyUI returned video from a different prompt")
                            raw = await self._request("GET", "/view", binary=True, params=ref)
                            # Container and decodability are independently verified by ffprobe/ffmpeg.
                            if raw[MP4_TYPE_START:MP4_TYPE_END] != b"ftyp":
                                raise ValueError("ComfyUI did not return an MP4 video")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            await asyncio.to_thread(temporary.write_bytes, raw)
                            temporary.replace(target)
                            complete = True
                            return {"provider": "comfyui_wan", "model": self.cfg.wan_unet, "prompt_id": prompt_id,
                                    "seed": seed, "frames": frames, "width": w, "height": h, "fps": self.cfg.fps}
                        if status.get("completed"):
                            raise ValueError("ComfyUI completed without a generated motion video")
                    await asyncio.sleep(self.cfg.comfy_poll_s)
        except httpx.HTTPError as exc:
            raise ValueError("Hollow's local motion service is unavailable") from exc
        except TimeoutError as exc:
            raise ValueError("Hollow motion exceeded its configured deadline") from exc
        finally:
            temporary.unlink(missing_ok=True)
            if not complete:
                await self._cancel(prompt_id)
