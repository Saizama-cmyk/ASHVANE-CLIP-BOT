"""Validate motion job ownership and decoded continuation using real ffmpeg media."""
import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from clipbot.config import Settings, ffmpeg_exe
from clipbot.story_motion import ComfyStoryMotion, motion_geometry, wan_workflow
from clipbot.story_render import StoryRenderer


def test_motion_geometry_respects_vae_strides_and_job_frame_cap():
    cfg = Settings().stories
    assert motion_geometry(720, 1280, 5, cfg) == (480, 864, 121)
    assert motion_geometry(1280, 720, 99, cfg) == (864, 480, 121)
    graph = wan_workflow('Paint slowly curls', 'Ashvane_Hollow/input.png', 480, 864, 121, cfg, 'Ashvane_Hollow/owned', 7)
    assert graph['latent']['inputs']['start_image'] == ['image', 0]
    assert graph['sample']['inputs']['model'] == ['sampling', 0]
    assert graph['video']['inputs']['fps'] == cfg.fps
    assert graph['save']['inputs']['format'] == 'mp4'
    assert graph['save']['inputs']['format.codec'] == 'h264'


@pytest.mark.parametrize('unsafe', [False, True])
def test_video_download_belongs_to_submitted_prompt_only(tmp_path, monkeypatch, unsafe):
    async def run():
        calls = []
        async def handle(req):
            body = json.loads(req.content) if req.content else {}
            calls.append((req.url.path, body))
            if req.url.path == '/prompt':
                assert str(uuid.UUID(body['prompt_id'])) == body['prompt_id']
                return httpx.Response(200, json={'prompt_id': body['prompt_id']})
            if req.url.path.startswith('/history/'):
                uid = req.url.path.rsplit('/', 1)[-1]
                return httpx.Response(200, json={uid: {'outputs': {'save': {'images': [{'filename': ('other' if unsafe else uid) + '_00001_.mp4', 'subfolder': 'Ashvane_Hollow', 'type': 'output'}]}}}})
            if req.url.path == '/view':
                return httpx.Response(200, content=b'\x00\x00\x00\x20ftypisom')
            return httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            gen = ComfyStoryMotion(http, 'http://127.0.0.1:8190', Settings().stories)
            async def upload(path): return 'Ashvane_Hollow/input.png'
            monkeypatch.setattr(gen, '_upload_reference', upload)
            if unsafe:
                with pytest.raises(ValueError, match='different prompt'):
                    await gen.generate_motion('test', tmp_path/'image.png', 720, 1280, 2, tmp_path/'out.mp4', seed=0)
                assert not (tmp_path/'out.mp4').exists()
                uid = next(body['prompt_id'] for path, body in calls if path == '/prompt')
                assert calls[-1] == ('/interrupt', {'prompt_id': uid})
            else:
                await gen.generate_motion('test', tmp_path/'image.png', 720, 1280, 2, tmp_path/'out.mp4', seed=0)
                assert (tmp_path/'out.mp4').is_file()
                assert not any(path in ('/interrupt', '/free') for path, _ in calls)
    asyncio.run(run())


@pytest.mark.parametrize('native', [False, True])
def test_finished_delivery_has_video_narration_and_correct_motion_label(tmp_path, monkeypatch, native):
    from array import array
    import math
    import wave
    async def run():
        settings = Settings()
        settings.stories.image_backend = 'comfyui'
        settings.stories.motion_backend = 'wan' if native else 'camera'
        settings.stories.image_width = settings.stories.image_height = 256
        settings.stories.captions = False
        if not ffmpeg_exe(settings): pytest.skip('ffmpeg unavailable')
        renderer = StoryRenderer(settings, None, asyncio.Lock())
        async def narration(*args):
            audio = tmp_path/'narration.wav'
            with wave.open(str(audio), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                wav.writeframes(array('h', (int(5000 * math.sin(2 * math.pi * 440 * t / 16000)) for t in range(16000))).tobytes())
            return [audio]
        async def illustrate(scene, folder, *args):
            folder.mkdir(parents=True)
            image = folder/'background.png'
            Image.new('RGB',(256,256),'blue').save(image)
            return {'background': image, 'full_frame':True}
        async def animate(scene, image, duration, *args):
            output=image.parent/'motion.mp4'
            await renderer._command([ffmpeg_exe(settings),'-v','error','-y','-f','lavfi','-i','testsrc2=size=256x256:rate=24','-t',str(duration),'-c:v','libx264',str(output)],settings)
            return output
        monkeypatch.setattr(renderer,'_narrate',narration)
        monkeypatch.setattr(renderer,'_illustrate',illustrate)
        monkeypatch.setattr(renderer,'_animate',animate)
        project={'id':'preview','format':'animated','duration_s':60,'scenes':[{'visual_prompt':'A room','narration':'I waited.'}]}
        result=await renderer(project,tmp_path,settings)
        duration, probe=await renderer._duration(Path(result['video_path']),settings)
        assert duration>=1 and {'video','audio'} <= {s['codec_type'] for s in probe['streams']}
        assert ('Generated scene animation' in result['visual_mode']) is native
        assert ('Illustrations use camera motion, not generated character animation.' in result['warnings']) is not native
    asyncio.run(run())


def test_long_narration_is_covered_by_continued_decodable_segments(tmp_path, monkeypatch):
    from clipbot import story_render as module
    async def run():
        settings = Settings()
        settings.stories.wan_max_frames = 49
        settings.stories.comfy_seed = 2**64 - 1
        if not ffmpeg_exe(settings): pytest.skip('ffmpeg unavailable')
        image = tmp_path/'background.png'
        Image.new('RGB', (64, 96), 'blue').save(image)
        renderer = StoryRenderer(settings, None, asyncio.Lock())
        async def ensure(*args): pass
        monkeypatch.setattr(renderer.visual_service, 'ensure', ensure)
        refs = []
        class Generator:
            def __init__(self, *args): pass
            async def generate_motion(self, prompt, reference, width, height, seconds, target, *, seed):
                refs.append(reference)
                assert 0 <= seed < 2**64
                assert reference.is_file()
                await renderer._command([ffmpeg_exe(settings), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=64x96:rate=24', '-t', str(seconds+0.1), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(target)], settings)
                return {'seed': seed}
        monkeypatch.setattr(module, 'ComfyStoryMotion', Generator)
        output = await renderer._animate({'visual_prompt':'A room', 'narration':'The paint curls.'}, image, 3.5, 64, 96, settings)
        seconds, probe = await renderer._duration(output, settings)
        assert len(refs) == 2 and refs[0] == image and refs[1].name == 'motion-last-0.png'
        assert seconds >= 3.5 and probe['streams'][0]['codec_type'] == 'video'
        assert len(json.loads((tmp_path/'motion.json').read_text())) == 2
    asyncio.run(run())
