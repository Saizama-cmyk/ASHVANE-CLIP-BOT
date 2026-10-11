"""Production failure controls: no invented hearing, unsafe forwarding or lost revisions."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
import httpx
import pytest

from clipbot.config import Settings, resolve_paths
from clipbot.music_api import MusicBridge, install_music_routes
from clipbot.music_producer import MusicProducer


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def test_corrupt_history_blocks_only_music_without_overwriting_it(tmp_path):
    ctx = context(tmp_path)
    path = ctx.paths.data / 'music-production-jobs.json'
    path.write_text('{broken', encoding='utf-8')
    app = FastAPI()
    install_music_routes(app, ctx)
    assert ctx.music_bridge.producer.error
    with pytest.raises(HTTPException) as exc:
        ctx.music_bridge.producer.create({'project_id': str(uuid.uuid4()), 'brief': 'A song'})
    assert exc.value.status_code == 409
    assert path.read_text(encoding='utf-8') == '{broken'


def context(tmp_path):
    settings = Settings()
    settings.app.data_dir = str(tmp_path)
    settings.businesses.resonance_enabled = True
    return SimpleNamespace(settings=settings, paths=resolve_paths(settings))


class Studio:
    def __init__(self, project, listener=True):
        self.project = project
        self.listener = listener
        self.calls = []

    def rewrite(self, value):
        return deepcopy(value)

    async def call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path.endswith('/validate'):
            assert set(payload) == {'summary', 'actions'}
            for action in payload['actions']:
                if action.get('type') != 'set_track' or action.get('track') != 'Drums':
                    raise HTTPException(422, 'Unknown edit operation or track')
            return payload
        if path.endswith('/edit'):
            revision = {'id': str(uuid.uuid4()), 'status': 'completed',
                        'audio_url': '/reaper/media/owned/revision',
                        'qc': {'non_silent': True, 'clipped_samples': 0}}
            self.project['revisions'].append(revision)
        if path.endswith('/listen'):
            if not self.listener:
                raise HTTPException(503, 'Listener unavailable; no listening occurred')
            return {'id': str(uuid.uuid4()), 'status': 'completed', 'listener_observation': 'Sparse drums and a warm bass line.'}
        return deepcopy(self.project)


async def finish(producer, job):
    task = producer.tasks[job['id']]
    await task
    return producer.get(job['id'])


@pytest.mark.anyio
async def test_plan_requires_native_validation_before_edit_and_does_not_claim_release(tmp_path):
    ctx = context(tmp_path)
    studio = Studio({'title': 'Original', 'tracks': [{'name': 'Drums', 'file': 'private.wav'}], 'revisions': []})
    producer = MusicProducer(ctx, studio)
    async def chat(contract, payload):
        if 'actions:array' in contract:
            assert 'file' not in payload['project']['tracks'][0]
            return {'summary': 'Lower drums', 'actions': [{'type': 'set_track', 'track': 'Drums', 'volume_db': -3}], 'needs_input': False, 'questions': []}
        assert payload['listener_observation']
        return {'summary': 'Audition needed', 'brief_alignment': 'Proposed gain change matches brief', 'issues': [], 'needs_human_input': False, 'revise': False}
    producer._chat = chat
    job = producer.create({'project_id': str(uuid.uuid4()), 'brief': 'Quieter drums'})
    result = await finish(producer, job)
    assert result['status'] == 'completed'
    assert result['review']['listener_available']
    assert result['review']['approved_for_release'] is False
    assert next(i for i, call in enumerate(studio.calls) if call[1].endswith('/validate')) < next(i for i, call in enumerate(studio.calls) if call[1].endswith('/edit'))


@pytest.mark.anyio
async def test_listener_unavailable_preserves_revision_and_requires_input(tmp_path):
    ctx = context(tmp_path)
    studio = Studio({'tracks': [], 'revisions': []}, listener=False)
    producer = MusicProducer(ctx, studio)
    async def chat(*_):
        return {'summary': 'Lower drums', 'actions': [{'type': 'set_track', 'track': 'Drums', 'volume_db': -3}], 'needs_input': False, 'questions': []}
    producer._chat = chat
    result = await finish(producer, producer.create({'project_id': str(uuid.uuid4()), 'brief': 'Quieter drums'}))
    assert result['status'] == 'needs_input'
    assert result['revision_id'] and result['revision']['status'] == 'completed'
    assert result['review']['listener_available'] is False
    assert result['review']['technical_pass'] is True


@pytest.mark.anyio
async def test_invalid_model_code_cannot_reach_native_edit(tmp_path):
    studio = Studio({'tracks': [], 'revisions': []})
    producer = MusicProducer(context(tmp_path), studio)
    async def chat(*_):
        return {'summary': 'Bad plan', 'actions': [{'type': 'run_script', 'code': 'delete_everything()'}], 'needs_input': False, 'questions': []}
    producer._chat = chat
    result = await finish(producer, producer.create({'project_id': str(uuid.uuid4()), 'brief': 'Make it better'}))
    assert result['status'] == 'failed'
    assert not any(call[1].endswith('/edit') for call in studio.calls)


@pytest.mark.anyio
async def test_manual_plan_and_missing_composition_do_not_render(tmp_path):
    studio = Studio({'tracks': [], 'revisions': []})
    producer = MusicProducer(context(tmp_path), studio)
    async def chat(*_):
        return {'summary': 'Need a vocal take', 'actions': [], 'needs_input': True, 'questions': ['Provide the intended vocal melody or a new take.']}
    producer._chat = chat
    result = await finish(producer, producer.create({'project_id': str(uuid.uuid4()), 'brief': 'Replace the singer'}))
    assert result['status'] == 'needs_input' and result['plan'] is None
    assert not any(call[0] == 'POST' for call in studio.calls)


@pytest.mark.anyio
async def test_cancel_and_restart_do_not_accept_interrupted_job(tmp_path):
    ctx = context(tmp_path)
    studio = Studio({'tracks': [], 'revisions': []})
    producer = MusicProducer(ctx, studio)
    entered = asyncio.Event()
    async def chat(*_):
        entered.set()
        await asyncio.Event().wait()
    producer._chat = chat
    job = producer.create({'project_id': str(uuid.uuid4()), 'brief': 'A restrained groove'})
    await entered.wait()
    assert (await producer.cancel(job['id']))['status'] == 'cancelled'
    producer.jobs[job['id']]['status'] = 'rendering'
    producer._save()
    restored = MusicProducer(ctx, studio)
    assert restored.get(job['id'])['status'] == 'needs_input'


@pytest.mark.anyio
async def test_immediate_cancel_is_durable_before_worker_starts(tmp_path):
    studio = Studio({'tracks': [], 'revisions': []})
    producer = MusicProducer(context(tmp_path), studio)
    job = producer.create({'project_id': str(uuid.uuid4()), 'brief': 'Quieter drums'})
    assert (await producer.cancel(job['id']))['status'] == 'cancelled'
    assert not studio.calls
    assert MusicProducer(producer.ctx, studio).get(job['id'])['status'] == 'cancelled'


@pytest.mark.anyio
async def test_cancel_after_native_accept_before_response_cancels_native(tmp_path):
    studio = Studio({'tracks': [], 'revisions': []})
    accepted = asyncio.Event()
    original = studio.call
    async def call(method, path, payload=None):
        if path.endswith('/edit'):
            studio.calls.append((method, path, payload))
            accepted.set()
            await asyncio.sleep(.02)
            return {'revisions': [{'id': 'accepted-revision'}]}
        return await original(method, path, payload)
    studio.call = call
    producer = MusicProducer(context(tmp_path), studio)
    async def chat(*_):
        return {'summary': 'Lower drums', 'actions': [{'type': 'set_track', 'track': 'Drums', 'volume_db': -3}], 'needs_input': False, 'questions': []}
    producer._chat = chat
    job = producer.create({'project_id': str(uuid.uuid4()), 'brief': 'Quieter drums'})
    await accepted.wait()
    assert (await producer.cancel(job['id']))['status'] == 'cancelled'
    assert any(path.endswith('/cancel') for _, path, _ in studio.calls)


@pytest.mark.anyio
async def test_cancel_waits_for_delayed_remote_edit_acceptance(tmp_path):
    studio = Studio({'tracks': [], 'revisions': []})
    dispatched = asyncio.Event()
    active = False
    cancelled_active = False
    original = studio.call
    async def call(method, path, payload=None):
        nonlocal active, cancelled_active
        if path.endswith('/edit'):
            dispatched.set()
            await asyncio.sleep(.02)
            active = True
            return {'revisions': [{'id': 'delayed-revision'}]}
        if path.endswith('/cancel'):
            cancelled_active = active
            active = False
        return await original(method, path, payload)
    studio.call = call
    producer = MusicProducer(context(tmp_path), studio)
    async def chat(*_):
        return {'summary': 'Lower drums', 'actions': [{'type': 'set_track', 'track': 'Drums', 'volume_db': -3}], 'needs_input': False, 'questions': []}
    producer._chat = chat
    job = producer.create({'project_id': str(uuid.uuid4()), 'brief': 'Quieter drums'})
    await dispatched.wait()
    result = await producer.cancel(job['id'])
    assert cancelled_active and not active
    assert result['status'] == 'cancelled' and result['revision_id'] == 'delayed-revision'


@pytest.mark.anyio
async def test_proxy_allowlist_disabled_writes_and_owned_url_rewrite(tmp_path):
    ctx = context(tmp_path)
    app = FastAPI()
    install_music_routes(app, ctx)
    calls = []
    async def local(method, path, payload=None):
        calls.append(path)
        return {'audio_url': '/media/owned', 'foreign_url': 'https://evil.example/payload'}
    ctx.music_bridge.call = local
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/music/arbitrary/file')).status_code == 404
        assert (await client.post('/api/music/exec', json={'cmd': 'bad'})).status_code == 404
        ctx.settings.businesses.resonance_enabled = False
        assert (await client.post('/api/music/create', json={})).status_code == 409
        response = await client.get('/api/music/songs')
        assert response.json() == {'audio_url': '/api/music/media/owned', 'foreign_url': ''}
        assert calls == ['/api/songs']
        assert (await client.post('/api/music/reaper/projects/'+str(uuid.uuid4())+'/validate', content='x'*ctx.settings.music.request_max_bytes+'x')).status_code == 413

