"""Private editorial notes must never become posts, even through legacy/manual paths."""
import asyncio
import json
import sqlite3

import pytest

from clipbot.config import Settings, resolve_paths
from clipbot.copywriter import Copywriter
from clipbot.db import Store
from clipbot.pipeline import Pipeline
from clipbot.public_copy import UnsafePublicCopy, check_public_text
from clipbot.scheduler import Scheduler, compose_post
from tests.test_scheduler import FakePub, cand, enabled, pubs


def test_legacy_copy_holds_without_an_upload_or_attempt(tmp_path):
    settings = enabled()
    store = Store(tmp_path / 'clips.db')
    clip = cand(tmp_path)
    clip.post_copy.pop('_source')
    store.upsert_candidate(clip)
    pub = FakePub(settings)
    scheduler = Scheduler(settings, store, pubs(settings, pub))
    try:
        result = asyncio.run(scheduler.publish_now(clip.id, ['discord']))
        assert not result['discord']['ok'] and 'public copy' in result['discord']['error'].lower()
        assert not pub.calls and not store.posts_for_candidate(clip.id)
    finally:
        store.close()


def test_clean_post_uses_public_copy_and_saves_immutable_sent_title(tmp_path):
    settings = enabled()
    store = Store(tmp_path / 'clips.db')
    clip = cand(tmp_path)
    clip.verdict['caption'] = 'The clip shows a routine in-game play with no distinct moment.'
    clip.post_copy['discord']['message'] = 'A very unexpected answer'
    store.upsert_candidate(clip)
    pub = FakePub(settings)
    scheduler = Scheduler(settings, store, pubs(settings, pub))
    try:
        assert asyncio.run(scheduler.publish_now(clip.id, ['discord']))['discord']['ok']
        assert pub.calls[0].title == 'A very unexpected answer'
        clip.post_copy['discord']['message'] = 'A later edit'
        store.upsert_candidate(clip)
        assert store.measurable_posts(0)[0]['title'] == 'A very unexpected answer'
        snapshot = json.loads(store.posts_for_candidate(clip.id)[0]['public_text'])
        assert 'routine' not in str(snapshot)
    finally:
        store.close()


def test_writer_never_sends_private_review_and_retries_private_output(tmp_path, monkeypatch):
    settings = Settings()
    settings.ai.retries = 1
    writer = Copywriter(settings, None)
    clip = cand(tmp_path)
    clip.verdict['reason'] = 'Six private words about editorial selection rationale.'
    clip.transcript = 'Is this cake edible?'
    seen = []
    async def chat(messages):
        seen.append(messages)
        assert clip.verdict['reason'] not in json.dumps(messages)
        text = clip.verdict['reason'] if len(seen) == 1 else 'Is this cake edible?'
        return json.dumps({'youtube': {'title': text, 'description': ''}})
    monkeypatch.setattr(writer, '_chat', chat)
    result = asyncio.run(writer.write(clip))
    assert len(seen) == 2 and result['_source'] == 'video'
    assert result['youtube']['title'] == 'Is this cake edible?'


@pytest.mark.parametrize('field', ['description', 'comment', 'hook'])
def test_private_text_in_any_public_field_is_rejected(tmp_path, field):
    settings = Settings()
    clip = cand(tmp_path)
    clip.verdict['reason'] = 'The smoke grenade offers no memorable payoff for viewers.'
    value = {'youtube': {field: clip.verdict['reason']}}
    with pytest.raises(UnsafePublicCopy, match='internal review'):
        check_public_text(clip, value, settings)


def test_public_hook_quoted_by_final_reviewer_and_source_dialogue_are_allowed(tmp_path):
    clip = cand(tmp_path)
    hook = 'He finally lands the impossible jump'
    clip.verdict['final_review'] = {'passed': True, 'evidence': [{'detail': 'The hook reads: ' + hook}]}
    clip.transcript = 'I can definitely make it this time'
    clip.verdict['reason'] = 'He says I can definitely make it this time before jumping.'
    check_public_text(clip, {'hook': hook, 'title': clip.transcript}, Settings())


def test_custom_description_template_cannot_leak_diagnostics(tmp_path):
    settings = Settings()
    settings.posting.caption_template = '{caption}\nJudge confidence: 0.7'
    with pytest.raises(UnsafePublicCopy, match='diagnostic'):
        compose_post(cand(tmp_path), settings, 'youtube')


def test_visible_hashtags_are_separate_from_youtube_metadata_tags(tmp_path):
    clip = cand(tmp_path)
    clip.post_copy['youtube']['hashtags'] = ['CounterStrike']
    clip.post_copy['youtube']['tags'] = ['xQc', 'xqc spelling']
    settings = Settings()
    settings.posting.caption_template = '{caption}\n{hashtags}'
    post = compose_post(clip, settings, 'youtube')
    assert '#CounterStrike' in post.caption and '#xQc' not in post.caption
    assert post.hashtags == ['xQc', 'xqc spelling']


def test_studio_and_final_gate_hold_private_hook_even_with_review_disabled(tmp_path):
    settings = Settings()
    settings.app.data_dir = str(tmp_path / 'data')
    settings.review.final_review = False
    pipeline = Pipeline(settings, resolve_paths(settings))
    clip = cand(tmp_path)
    clip.post_copy['hook'] = 'Judge confidence: 0.7'
    pipeline.store.upsert_candidate(clip)
    try:
        assert asyncio.run(pipeline._review_final(clip)) is False
        with pytest.raises(UnsafePublicCopy):
            asyncio.run(pipeline.studio_render(clip.id, {}, 0, 1, clip.post_copy['hook'], False))
    finally:
        pipeline.store.close()


def test_old_posts_migrate_without_learning_judge_titles(tmp_path):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL, platform TEXT NOT NULL, remote_id TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', posted_at REAL NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '')")
    store = Store(path)
    clip = cand(tmp_path)
    try:
        store.upsert_candidate(clip)
        store.record_post(clip.id, 'youtube', 'old', '', 'ok', when=1)
        assert store.measurable_posts(0)[0]['title'] == ''
    finally:
        store.close()
