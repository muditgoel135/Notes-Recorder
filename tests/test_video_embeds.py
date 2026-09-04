from types import SimpleNamespace

from services import video_embeds


def test_video_embed_parsing_supports_youtube_and_vimeo():
    embeds = video_embeds.extract_video_embeds(
        '<iframe src="https://www.youtube.com/embed/abc" title="Physics"></iframe>'
        '<iframe src="https://player.vimeo.com/video/42"></iframe>'
        '<iframe src="https://evil.example/embed/nope"></iframe>'
    )
    assert embeds == [
        {
            "host": "youtube",
            "video_id": "abc",
            "url": "https://www.youtube.com/watch?v=abc",
            "title": "Physics",
        },
        {
            "host": "vimeo",
            "video_id": "42",
            "url": "https://vimeo.com/42",
            "title": "vimeo video",
        },
    ]


def test_video_transcription_parsing_and_formatting_skips_invalid_entries():
    note = SimpleNamespace(
        video_transcriptions=(
            '{"one":{"title":"Demo","transcript":" text "},'
            '"two":{"transcript":""},"three":"invalid"}'
        )
    )
    assert video_embeds.format_video_transcripts(note) == (
        "[Embedded video: Demo]\ntext"
    )
    assert video_embeds.parse_video_transcriptions("not json") == {}
    assert video_embeds.parse_video_transcriptions("[]") == {}


def test_merge_video_transcript_is_idempotent(monkeypatch):
    note = SimpleNamespace(transcription="recording")
    monkeypatch.setattr(video_embeds, "refresh_note_search_index", lambda note: None)
    video_embeds._merge_video_transcript(note, "Demo", "video text")
    video_embeds._merge_video_transcript(note, "Demo", "video text")
    assert note.transcription.count("[Embedded video: Demo]") == 1
    assert "video text" in note.transcription


def test_process_video_embeds_reuses_processed_data_and_deduplicates_frames(
    test_app, tmp_recordings, monkeypatch
):
    from core.extensions import db
    from core.models import Note

    with test_app.app_context():
        note = Note(
            date="2026-09-03",
            time="10:00:00",
            start_time="10:00:00",
            subject="Physics",
            notes_html='<iframe src="https://youtube.com/embed/abc"></iframe>',
            transcription="recording",
            transcription_status="pending",
            key_points_status="pending",
        )
        db.session.add(note)
        db.session.commit()
        monkeypatch.setattr(
            video_embeds,
            "_process_embed",
            lambda embed, cache_dir, note: ("video text", "Fetched title"),
        )
        frame = (
            __import__("pathlib").Path(tmp_recordings.video_cache)
            / "youtube-abc"
            / "frames"
            / "frame_001.jpg"
        )
        frame.parent.mkdir(parents=True)
        frame.write_bytes(b"frame")
        monkeypatch.setattr(video_embeds, "_encode_image", lambda path: "encoded")

        images = video_embeds.process_video_embeds(note)
        assert images == ["encoded"]
        assert "video text" in note.transcription
        assert "Fetched title" in note.video_transcriptions
