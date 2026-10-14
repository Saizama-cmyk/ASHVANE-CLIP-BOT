import asyncio
import copy
from types import SimpleNamespace
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from clipbot.clip_feedback import correction_record, correction_summary, evaluate_correction_trial, install_clip_feedback_routes
from clipbot.config import Settings
from clipbot.db import Store
from clipbot.models import Stage
from tests.test_growth import cand


def test_feedback_survives_cleanup_and_label_edit_preserves_original_evidence(tmp_path):
    settings = Settings()
    store = Store(tmp_path / 'db')
    candidate = cand()
    candidate.stage = Stage.REJECTED
    candidate.verdict.update(passed=False, reason='No payoff')
    candidate.transcript = 'A quiet but specific payoff'
    store.upsert_candidate(candidate)
    original = copy.deepcopy(candidate.to_dict())
    try:
        saved = store.save_correction(correction_record(candidate, 'default', {'label': 'good', 'note': 'Wrong rejection'}, settings), 100)
        assert correction_summary([saved])['wrong_rejections'] == 1
        assert store.get_candidate(candidate.id).to_dict() == original
        candidate.verdict['passed'] = True
        settings.review.feedback_eval_percent = 50
        changed = store.save_correction(correction_record(candidate, 'default', {'label': 'bad', 'note': 'Changed my view'}, settings), 100)
        assert changed['evidence'] == saved['evidence'] and changed['split'] == saved['split']
        store.delete_candidate(candidate.id)
        assert store.get_candidate(candidate.id) is None
        assert store.corrections_for('default')[0]['note'] == 'Changed my view'
        assert store.corrections_for('a' * 32) == []
        assert correction_summary(store.corrections_for('default'))['automatic_tuning'] is False
    finally:
        store.close()


def test_overlapping_sources_share_split_across_hour_boundary_and_limit_preserves_labels(tmp_path):
    settings = Settings()
    store = Store(tmp_path / 'db')
    first, second = cand(), cand()
    first.start_wall, first.end_wall, first.event.t_wall = 3580, 3620, 3590
    second.start_wall, second.end_wall, second.event.t_wall = 3600, 3640, 3610
    try:
        one = store.save_correction(correction_record(first, 'default', {'label': 'good'}, settings), 2)
        row = correction_record(second, 'default', {'label': 'bad'}, settings)
        row['split'] = 'training' if one['split'] == 'evaluation' else 'evaluation'
        two = store.save_correction(row, 2)
        assert two['source_group'] == one['source_group'] and two['split'] == one['split']
        with pytest.raises(ValueError, match='preserved'):
            store.save_correction(correction_record(cand(), 'default', {'label': 'good'}, settings), 2)
        assert len(store.corrections_for('default')) == 2
    finally:
        store.close()


def test_trial_requires_real_balanced_holdout_and_cannot_auto_apply():
    cfg = Settings().review
    cfg.feedback_min_per_label = 1
    rows = [{'candidate_id': 'good', 'split': 'evaluation', 'label': 'good', 'evidence': {'automatic_passed': False}},
            {'candidate_id': 'bad', 'split': 'evaluation', 'label': 'bad', 'evidence': {'automatic_passed': False}},
            {'candidate_id': 'train', 'split': 'training', 'label': 'good', 'evidence': {'automatic_passed': False}}]
    assert not evaluate_correction_trial(rows[:1], {'good': True}, cfg)['qualified']
    assert not evaluate_correction_trial(rows, {'good': True}, cfg)['qualified']
    assert not evaluate_correction_trial(rows, {'good': True, 'bad': True}, cfg)['qualified']
    result = evaluate_correction_trial(rows, {'good': True, 'bad': False}, cfg)
    assert result['qualified'] and result['accuracy_gain'] == .5 and result['automatic_apply'] is False
    assert result['candidate'] == {'false_accepts': 0, 'false_rejections': 0}


def test_profile_and_payload_boundaries_and_no_publishing(tmp_path):
    async def run():
        settings = Settings()
        store = Store(tmp_path / 'db')
        mine, other = cand(), cand(source={'account_profile_id': 'a' * 32})
        store.upsert_candidate(mine); store.upsert_candidate(other)
        holds = []
        class Profiles:
            def active_id(self, business): return 'default'
            def require_current(self, business, expected):
                if expected != 'default': raise HTTPException(409, 'Account profile changed')
            @asynccontextmanager
            async def upload(self, business):
                holds.append(True)
                try: yield
                finally: holds.pop()
        ctx = SimpleNamespace(settings=settings, pipeline=SimpleNamespace(store=store, account_profiles=Profiles()))
        app = FastAPI(); install_clip_feedback_routes(app, ctx)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                headers = {'X-Account-Profile': 'default'}
                saved = await client.put('/api/clip-feedback/' + mine.id, headers=headers, json={'label': 'good', 'preview_s': 1})
                assert saved.status_code == 200 and holds == []
                wrong = await client.put('/api/clip-feedback/' + other.id, headers=headers, json={'label': 'good'})
                assert wrong.status_code == 422
                stale = await client.put('/api/clip-feedback/' + mine.id, headers={'X-Account-Profile': 'a' * 32}, json={'label': 'bad'})
                assert stale.status_code == 409
                invalid = await client.put('/api/clip-feedback/' + mine.id, headers=headers,
                                           content=b'{"label":"good","preview_s":1e9999}')
                assert invalid.status_code == 422
                assert store.get_candidate(mine.id).stage == Stage.SCHEDULED
                assert store.recent_posts(10) == []
        finally: store.close()
    asyncio.run(run())
