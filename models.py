from collections import defaultdict

from extensions import db
from config import TRANSCRIPTION_PENDING, KEY_POINTS_PENDING

SPEAKER_COLOR_PALETTE = [
    "#4c78a8",
    "#f58518",
    "#54a24b",
    "#e45756",
    "#72b7b2",
    "#eeca3b",
    "#b279a2",
    "#ff9da6",
]


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)
    time = db.Column(db.String(8), nullable=False)
    start_time = db.Column(db.String(8), nullable=False)
    end_time = db.Column(db.String(8), nullable=True)
    subject = db.Column(db.String(100), nullable=True)
    recording_path = db.Column(db.String(200), nullable=True)
    transcription = db.Column(db.Text, nullable=True)
    transcription_segments = db.Column(db.Text, nullable=True)
    transcription_status = db.Column(
        db.String(20), nullable=False, default=TRANSCRIPTION_PENDING
    )
    transcription_progress = db.Column(db.Integer, nullable=True, default=0)

    transcription_error = db.Column(db.Text, nullable=True)
    title = db.Column(db.String(200), nullable=True)
    key_points = db.Column(db.Text, nullable=True)
    key_points_status = db.Column(
        db.String(20), nullable=False, default=KEY_POINTS_PENDING
    )

    key_points_error = db.Column(db.Text, nullable=True)
    tags = db.relationship("Tag", secondary="note_tags", backref="notes")
    speakers = db.relationship(
        "Speaker",
        order_by="Speaker.order_index",
        cascade="all, delete-orphan",
        backref="note",
    )

    def speakers_by_order(self):
        return {speaker.order_index: speaker for speaker in self.speakers}


class RecordingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_key = db.Column(db.String(32), nullable=False, unique=True, index=True)
    subject = db.Column(db.String(100), nullable=True)
    start_time = db.Column(db.String(8), nullable=False)
    end_time = db.Column(db.String(8), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")
    mime_type = db.Column(db.String(100), nullable=True)
    extension = db.Column(db.String(10), nullable=False, default="webm")
    chunk_count = db.Column(db.Integer, nullable=False, default=0)
    segments_json = db.Column(db.Text, nullable=True)
    note_id = db.Column(db.Integer, db.ForeignKey("note.id"), nullable=True)
    note = db.relationship("Note", backref="recording_session", uselist=False)

    def to_dict(self):
        return {
            "id": self.id,
            "session_key": self.session_key,
            "subject": self.subject,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "mime_type": self.mime_type,
            "extension": self.extension,
            "chunk_count": self.chunk_count,
            "note_id": self.note_id,
        }


class Speaker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.Integer, db.ForeignKey("note.id"), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(50), nullable=False)
    display_name = db.Column(db.String(100), nullable=True)
    color = db.Column(db.String(7), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "order_index": self.order_index,
            "label": self.label,
            "display_name": self.display_name,
            "color": self.color,
        }


class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    def to_dict(self):
        return {"id": self.id, "name": self.name}


note_tags = db.Table(
    "note_tags",
    db.Column("note_id", db.Integer, db.ForeignKey("note.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True),
)


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("tag.id"), nullable=True)
    parent = db.relationship("Tag", remote_side=[id], backref="children")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "parent_id": self.parent_id,
        }


def get_tag_descendant_ids(root_ids):
    """Return root_ids plus all descendant tag ids."""
    children_by_parent = defaultdict(list)
    for tag_id, parent_id in Tag.query.with_entities(Tag.id, Tag.parent_id).all():
        children_by_parent[parent_id].append(tag_id)

    result = set(root_ids)
    stack = list(root_ids)
    while stack:
        current = stack.pop()
        for child_id in children_by_parent.get(current, []):
            if child_id not in result:
                result.add(child_id)
                stack.append(child_id)
    return result
