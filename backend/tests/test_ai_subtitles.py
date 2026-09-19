from app.ai_subtitles import _priority, parse_subtitles, subtitles_to_srt, subtitles_to_txt
from app.ai_models import TranscriptCue


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


def test_subtitles_to_srt_uses_standard_timestamps_and_utf8_text():
    document = subtitles_to_srt([
        TranscriptCue(start=1.2345, end=65.01, text="第一行"),
        TranscriptCue(start=3661, end=3662.5, text="第二行"),
    ])

    assert document == (
        "1\n00:00:01,234 --> 00:01:05,010\n第一行\n\n"
        "2\n01:01:01,000 --> 01:01:02,500\n第二行\n"
    )

def test_subtitles_to_txt_contains_only_transcript_text():
    assert subtitles_to_txt([TranscriptCue(start=0, end=1, text="第一行"), TranscriptCue(start=1, end=2, text="第二行")]) == "第一行\n第二行\n"
