"""Vendor selected, pinned public UI assets and retain their licenses."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'clipbot/dashboard/static'
THREE_VERSION = '0.186.1'
THREE_ROOT = STATIC / 'vendor/three' / THREE_VERSION


def main():
    records = []
    with httpx.Client(timeout=30, follow_redirects=False) as http:
        def save(url, target):
            response = http.get(url)
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError('Unexpectedly large UI dependency')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
            records.append({'path': target.relative_to(ROOT).as_posix(), 'url': url,
                            'sha256': hashlib.sha256(response.content).hexdigest()})
            return response.text
        pending = ['postprocessing/EffectComposer.js', 'postprocessing/RenderPass.js',
                   'postprocessing/UnrealBloomPass.js', 'postprocessing/OutputPass.js']
        seen = set()
        while pending:
            relative = pending.pop()
            if relative in seen:
                continue
            if len(seen) >= 40 or '..' in Path(relative).parts:
                raise ValueError('Unexpected addon dependency tree')
            seen.add(relative)
            target = THREE_ROOT / 'examples/jsm' / relative
            original = save(f'https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/examples/jsm/{relative}', target)
            for specifier in re.findall(r"from\s+['\"]([^'\"]+)['\"]", original):
                if specifier == 'three':
                    import os
                    replacement = Path(os.path.relpath(THREE_ROOT / 'build/three.module.js', target.parent)).as_posix()
                    original = original.replace("from 'three'", f"from '{replacement}'").replace('from "three"', f'from "{replacement}"')
                elif specifier.startswith('three/addons/'):
                    import os
                    addon = specifier.removeprefix('three/addons/')
                    dependency = THREE_ROOT / 'examples/jsm' / addon
                    replacement = Path(os.path.relpath(dependency, target.parent)).as_posix()
                    if not replacement.startswith('.'):
                        replacement = './' + replacement
                    original = original.replace("from '" + specifier + "'", "from '" + replacement + "'")
                    pending.append(addon)
                elif specifier.startswith('.'):
                    dependency = (target.parent / specifier).resolve()
                    if not dependency.is_relative_to((THREE_ROOT / 'examples/jsm').resolve()):
                        raise ValueError('Addon import escapes expected package')
                    pending.append(dependency.relative_to((THREE_ROOT / 'examples/jsm').resolve()).as_posix())
                else:
                    raise ValueError('Unexpected third-party import: ' + specifier)
            target.write_text(original, encoding='utf-8', newline='\n')
            records[-1]['installed_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        save(f'https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/LICENSE', THREE_ROOT / 'LICENSE')
        for family, filename in [('spacegrotesk', 'SpaceGrotesk[wght].ttf'),
                                 ('ibmplexsans', 'IBMPlexSans[wdth,wght].ttf')]:
            base = 'https://raw.githubusercontent.com/google/fonts/main/ofl/' + family + '/'
            save(base + quote(filename), STATIC / 'fonts' / filename)
            save(base + 'OFL.txt', STATIC / 'fonts' / (family + '-OFL.txt'))
    (STATIC / 'vendor/observatory-assets.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(json.dumps({'vendored_files': len(records), 'three_version': THREE_VERSION}))


if __name__ == '__main__':
    main()
