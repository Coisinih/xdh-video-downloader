from app.ai_subtitles import ResolvedTrack, _priority, parse_subtitles
from app.ai_models import SubtitleTrack


def test_chinese_manual_track_has_highest_priority():
    assert _priority("zh-CN", False) < _priority("zh-CN", True)
    assert _priority("zh-CN", False) < _priority("en", False)


def test_parse_webvtt_strips_markup_and_duplicate_cues():
    cues = parse_subtitles("""WEBVTT

00:00:01.000 --> 00:00:03.500
<b>第一行</b>

2
00:00:04,000 --> 00:00:05,000 align:start
第二行

00:00:04,000 --> 00:00:05,000
第二行
""")
    assert [(cue.start, cue.end, cue.text) for cue in cues] == [(1, 3.5, "第一行"), (4, 5, "第二行")]


def test_parse_bilibili_json_subtitles():
    cues = parse_subtitles('{"body":[{"from":1.5,"to":3,"content":"<b>你好</b>"}]}')
    assert [(cue.start, cue.end, cue.text) for cue in cues] == [(1.5, 3, "你好")]
