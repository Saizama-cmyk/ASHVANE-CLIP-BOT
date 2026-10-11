"""Titles that describe the clip get caught; titles that hook get through."""
from clipbot.config import Settings
from clipbot.copywriter import narrates, clip_brief


def test_describing_titles_are_caught_and_hooks_pass():
    patterns = [r"\breacts? to\b", r"\brants? about\b", r"\blaughs? (at|so)\b", r"\btalks? about\b",
                r"\bchat (goes|went|gets|got|loses|lost)\b"]
    describing = ["Jynxzi laughs so hard he covers his mouth", "Tony Corleone rants about paper units",
                  "Xaryu says Dray-Nai and chat loses it", "Zackrawrr Reacts to Singapore Bus Fine Tweet",
                  "She Smiled While Chat Went Nuclear"]
    hooks = ['"I\'m never doing that again"', "He was one hit away...", "xQc was NOT ready for this"]
    for title in describing:
        assert narrates({"youtube": {"title": title}}, patterns), title
    for title in hooks:
        assert narrates({"youtube": {"title": title}}, patterns) == "", title


def test_a_broken_pattern_is_skipped_not_fatal():
    assert narrates({"hook": "chat went wild"}, ["(unclosed", r"\bchat went\b"]) == "chat went"


def test_factual_conversation_titles_do_not_trigger_default_extra_model_call():
    assert narrates({"youtube": {"title": "Kai reacts to the cake misunderstanding"}},
                    Settings().copywriter.narration) == ""


def test_writer_brief_excludes_all_private_review_and_discovery_notes(tmp_path):
    from tests.test_scheduler import cand
    c = cand(tmp_path)
    c.verdict["viewer_review"] = {"why_watch": "He notices the cake is edible and laughs.",
                                   "evidence": [{"at": 12, "detail": "The misunderstanding resolves."}]}
    c.source = {"url": "https://clips.twitch.tv/original"}
    c.visual = 'Private visual assessment should never be exported.'
    c.verdict['reason'] = 'Private judgment on why this moment was clipped.'
    c.event.chat_sample = ['Private chat spike message']
    c.transcript = '[0.0-0.9] Is this cake edible?'
    brief = clip_brief(c, "Style examples, not facts about this video", 0)
    assert "https://clips.twitch.tv/original" in brief
    assert 'Is this cake edible?' in brief
    for secret in ['He notices', 'The misunderstanding resolves', 'Private visual',
                   'Private judgment', 'Private chat', 'Big W', 'wow']:
        assert secret not in brief
