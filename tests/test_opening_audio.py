"""Added static is held; the same noisy source/game audio remains eligible."""
import asyncio
from pathlib import Path
import subprocess
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from clipbot.audio_review import check_opening_audio, noise_summary
from clipbot.config import Settings


def pcm(noise=False):
    rate = Settings().review.opening_audio_rate
    t = np.arange(rate * 2) / rate
    samples = np.random.default_rng(4).normal(0, .25, len(t)) if noise else .2 * np.sin(2 * np.pi * 440 * t)
    return samples.astype('<f4')


def test_spectrum_does_not_call_silence_or_tones_static():
    settings = Settings()
    assert noise_summary(pcm().tobytes(), settings)['noise_share'] == 0
    assert noise_summary(np.zeros(32000, dtype='<f4').tobytes(), settings)['noise_share'] == 0
    assert noise_summary(pcm(True).tobytes(), settings)['noise_share'] > .9
    with pytest.raises(ValueError):
        noise_summary(np.full(32000, np.nan, dtype='<f4').tobytes(), settings)


@pytest.mark.parametrize('source_noise,export_noise,expected', [(False, True, False), (True, True, True), (False, False, True)])
def test_real_aac_decode_compares_aligned_source(tmp_path, ffmpeg, source_noise, export_noise, expected):
    settings = Settings()
    settings.paths.ffmpeg = ffmpeg
    def save(path, samples):
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(settings.review.opening_audio_rate)
            wav.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
    source, intermediate, final = tmp_path / 'source.wav', tmp_path / 'edit.wav', tmp_path / 'final.m4a'
    # Leading source noise must be skipped according to the saved edit timeline.
    save(source, np.concatenate([pcm(True), pcm(source_noise)]))
    save(intermediate, pcm(export_noise))
    subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-i', str(intermediate), '-c:a', 'aac', '-b:a', '128k', str(final)], check=True)
    candidate = SimpleNamespace(raw_path=str(source), final_path=str(final))
    result = asyncio.run(check_opening_audio(candidate, {'source_start': 2, 'keeps': [[0, 2]], 'intro_s': 0}, settings))
    assert result['status'] == 'complete', result
    assert result['passed'] is expected, result


def test_missing_source_is_explicit_without_fake_listening(tmp_path):
    c = SimpleNamespace(raw_path=str(tmp_path / 'gone.wav'), final_path='ignored')
    result = asyncio.run(check_opening_audio(c, {'keeps': [[0, 1]], 'intro_s': 0}, Settings()))
    assert result['status'] == 'unavailable' and result['passed'] is None
