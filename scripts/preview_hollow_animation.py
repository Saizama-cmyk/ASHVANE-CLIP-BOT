"""Exercise actual installed Wan scene motion using the verified illustration and narration."""
import asyncio
import json
import shutil
import time
import os
from pathlib import Path

import httpx

from preview_hollow_visuals import ROOT, installed_settings
from clipbot.story_render import StoryRenderer


async def main():
    settings = installed_settings()
    settings.stories.motion_backend = 'wan'
    settings.stories.motion_style_prompt = ('One continuous locked-off shot. Keep the original composition, sharp focus, lighting and exposure fixed from beginning to end. '
        'Animate the specifically described physical change in the visible subject, not camera movement or changes in focus. Preserve the original materials, props and architecture. '
        'No new objects, people, cuts, zoom, rack focus, blur, text or lip sync. Follow the visible event with slow, purposeful movement.')
    settings.stories.wan_negative_prompt += ', defocus, rack focus, blurred frame, camera movement, static subject'
    settings.stories.comfy_motion_models_root = str(Path(os.environ['LOCALAPPDATA']) / 'Ashvane/models/hollow-motion')
    source = ROOT / 'artifacts/hollow-quality/cinematic-wall-varied-preview'
    folder = ROOT / 'artifacts/hollow-quality/wan-paint-focused-preview'
    folder.mkdir(parents=True, exist_ok=True)
    scene = json.loads((source/'plan.json').read_text())['scenes'][1]
    scene['visual_prompt'] = ('Locked macro close-up of old cream paint peeling from a petrol-blue plaster wall beside a warm tungsten lamp. '
        'A loose central strip of paint slowly bends outward and curls downward, exposing more of the rusty-red underlayer. '
        'The paint flexes visibly while the wall, lamp, lighting and camera remain still. Sharp focus stays on the peeling strip for the entire shot.')
    project = {'id':'hollow-motion-preview','title':'The wall is peeling','format':'animated','duration_s':60,'scenes':[scene]}
    async with httpx.AsyncClient(trust_env=False) as http:
        renderer = StoryRenderer(settings, http, asyncio.Lock())
        async def narration(*args):
            audio = folder/'narration-0.wav'
            shutil.copy2(source/'narration-1.wav', audio)
            shutil.copy2(source/'narration-1.timings.json', audio.with_suffix('.timings.json'))
            return [audio]
        async def illustration(scene, target, width, height, settings, reference=None):
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source/'scene-1/background.png', target/'background.png')
            return {'background':target/'background.png','full_frame':True}
        renderer._narrate = narration
        renderer._illustrate = illustration
        renderer.progress = lambda *args: print('Progress', args, flush=True)
        started=time.monotonic()
        try:
            result=await renderer(project, folder, settings)
            result['render_elapsed_s']=round(time.monotonic()-started,2)
            (folder/'result.json').write_text(json.dumps(result,indent=2))
            print(json.dumps(result),flush=True)
        finally:
            await renderer.stop()


if __name__ == '__main__':
    asyncio.run(main())
