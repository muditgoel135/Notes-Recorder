import base64
from types import SimpleNamespace

from services import note_images


def test_extract_rich_note_images_sanitizes_and_extracts_attributes():
    images = note_images.extract_rich_note_images(
        '<p><img src="data:image/png;base64,aGVsbG8=" alt=" Diagram ">'
        '<img src="javascript:alert(1)"></p>'
    )
    assert images == [{"src": "data:image/png;base64,aGVsbG8=", "alt": "Diagram"}]


def test_local_image_path_requires_existing_supported_in_tree_file(tmp_path, monkeypatch):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_path = image_dir / "diagram.png"
    image_path.write_bytes(b"png-data")
    monkeypatch.setattr(note_images, "NOTE_IMAGES_DIR", str(image_dir))

    resolved = note_images.note_image_path_from_src(
        "/recordings/note_images/diagram.png"
    )
    assert resolved == str(image_path)
    assert note_images.note_image_path_from_src(
        "/recordings/note_images/../secret.png"
    ) is None
    assert note_images.note_image_path_from_src(
        "/recordings/note_images/missing.png"
    ) is None
    assert note_images.note_image_path_from_src(
        "/recordings/note_images/diagram.txt"
    ) is None
    assert note_images.note_image_path_from_src("https://example.com/a.png") is None


def test_ollama_image_from_src_supports_data_and_local_files(tmp_path, monkeypatch):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "diagram.png").write_bytes(b"png-data")
    monkeypatch.setattr(note_images, "NOTE_IMAGES_DIR", str(image_dir))

    assert note_images.ollama_image_from_src(
        "data:image/png;base64,aG Vs bG8="
    ) == "aGVsbG8="
    assert note_images.ollama_image_from_src(
        "/recordings/note_images/diagram.png"
    ) == base64.b64encode(b"png-data").decode("ascii")
    assert note_images.ollama_image_from_src("data:text/plain;base64,abc") is None


def test_collect_ollama_note_images_deduplicates(monkeypatch):
    monkeypatch.setattr(
        note_images,
        "extract_rich_note_images",
        lambda html: [{"src": "one"}, {"src": "two"}],
    )
    monkeypatch.setattr(
        note_images,
        "ollama_image_from_src",
        lambda src: "same" if src in {"one", "two"} else None,
    )
    notes = [SimpleNamespace(notes_html="<p>x</p>")]
    assert note_images.collect_ollama_note_images(notes) == ["same"]
