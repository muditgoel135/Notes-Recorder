"""

Database models for the Flask app.

"""

# Import required modules
from collections import defaultdict
from datetime import datetime

# Import the database instance and config constants
from core.extensions import db
from core.config import TRANSCRIPTION_PENDING, KEY_POINTS_PENDING, DEFAULT_UNIT

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
    """
    Represents a recorded note, containing transcription, key points, and associated metadata.
    """

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)
    time = db.Column(db.String(8), nullable=False)
    start_time = db.Column(db.String(8), nullable=False)
    end_time = db.Column(db.String(8), nullable=True)
    subject = db.Column(db.String(100), nullable=True)
    unit = db.Column(db.String(100), nullable=True, default=DEFAULT_UNIT)
    recording_path = db.Column(db.String(200), nullable=True)
    notes_html = db.Column(db.Text, nullable=True)
    transcription = db.Column(db.Text, nullable=True)
    transcription_segments = db.Column(db.Text, nullable=True)
    transcription_status = db.Column(
        db.String(20), nullable=False, default=TRANSCRIPTION_PENDING
    )

    transcription_progress = db.Column(db.Integer, nullable=True, default=0)
    transcription_stage = db.Column(db.String(20), nullable=True)

    transcription_error = db.Column(db.Text, nullable=True)
    bookmarks_json = db.Column(db.Text, nullable=True)
    video_transcriptions = db.Column(db.Text, nullable=True)
    title = db.Column(db.String(200), nullable=True)
    key_points = db.Column(db.Text, nullable=True)
    key_points_status = db.Column(
        db.String(20), nullable=False, default=KEY_POINTS_PENDING
    )

    key_points_generation = db.Column(db.Integer, nullable=False, default=0)

    key_points_error = db.Column(db.Text, nullable=True)
    pinned = db.Column(db.Boolean, nullable=False, default=False)
    tags = db.relationship("Tag", secondary="note_tags", backref="notes")
    speakers = db.relationship(
        "Speaker",
        order_by="Speaker.order_index",
        cascade="all, delete-orphan",
        backref="note",
    )

    def speakers_by_order(self):
        """
        Return the note's speakers keyed by their order index.

        :return: A dict mapping order index to Speaker instance.
        :rtype: dict of int to Speaker
        """

        return {speaker.order_index: speaker for speaker in self.speakers}


class RecordingSession(db.Model):
    """
    Represents a recording session that manages uploaded audio chunks before
    they are assembled into a Note.
    """

    id = db.Column(db.Integer, primary_key=True)
    session_key = db.Column(db.String(32), nullable=False, unique=True, index=True)
    subject = db.Column(db.String(100), nullable=True)
    unit = db.Column(db.String(100), nullable=True, default=DEFAULT_UNIT)
    start_time = db.Column(db.String(8), nullable=False)
    end_time = db.Column(db.String(8), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")
    mime_type = db.Column(db.String(100), nullable=True)
    extension = db.Column(db.String(10), nullable=False, default="webm")
    chunk_count = db.Column(db.Integer, nullable=False, default=0)
    segments_json = db.Column(db.Text, nullable=True)
    notes_html = db.Column(db.Text, nullable=True)
    bookmarks_json = db.Column(db.Text, nullable=True)
    note_id = db.Column(db.Integer, db.ForeignKey("note.id"), nullable=True)
    note = db.relationship("Note", backref="recording_session", uselist=False)

    def to_dict(self):
        """
        Convert the recording session to a serializable dictionary.

        :return: A dict of the session's key attributes.
        :rtype: dict
        """

        return {
            "id": self.id,
            "session_key": self.session_key,
            "subject": self.subject,
            "unit": self.unit or DEFAULT_UNIT,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "mime_type": self.mime_type,
            "extension": self.extension,
            "chunk_count": self.chunk_count,
            "notes_html": self.notes_html or "",
            "bookmarks_json": self.bookmarks_json or "[]",
            "note_id": self.note_id,
        }


class Speaker(db.Model):
    """
    Represents a speaker identified during diarization of a note's recording.
    """

    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.Integer, db.ForeignKey("note.id"), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(50), nullable=False)
    display_name = db.Column(db.String(100), nullable=True)
    color = db.Column(db.String(7), nullable=False)

    def to_dict(self):
        """
        Convert the speaker to a serializable dictionary.

        :return: A dict of the speaker's key attributes.
        :rtype: dict
        """

        return {
            "id": self.id,
            "order_index": self.order_index,
            "label": self.label,
            "display_name": self.display_name,
            "color": self.color,
        }


class Subject(db.Model):
    """
    Represents a subject that can be assigned to notes.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    units = db.relationship(
        "Unit",
        order_by="Unit.name",
        cascade="all, delete-orphan",
        backref="subject",
    )

    def to_dict(self):
        """
        Convert the subject to a serializable dictionary.

        :return: A dict of the subject's id and name.
        :rtype: dict
        """

        return {"id": self.id, "name": self.name}


class Unit(db.Model):
    """
    Represents a unit (chapter) within a subject that can be assigned to notes.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("subject_id", "name"),)

    def to_dict(self):
        """
        Convert the unit to a serializable dictionary.

        :return: A dict of the unit's id, name, and subject id.
        :rtype: dict
        """

        return {"id": self.id, "name": self.name, "subject_id": self.subject_id}


note_tags = db.Table(
    "note_tags",
    db.Column("note_id", db.Integer, db.ForeignKey("note.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True),
)

chat_session_notes = db.Table(
    "chat_session_notes",
    db.Column(
        "chat_session_id",
        db.Integer,
        db.ForeignKey("chat_session.id"),
        primary_key=True,
    ),
    db.Column("note_id", db.Integer, db.ForeignKey("note.id"), primary_key=True),
)


class ChatSession(db.Model):
    """
    Represents a chat conversation over a set of selected notes.
    """

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    notes = db.relationship(
        "Note",
        secondary=chat_session_notes,
        backref=db.backref("chat_sessions", lazy="dynamic"),
    )

    messages = db.relationship(
        "ChatMessage",
        order_by="ChatMessage.created_at",
        cascade="all, delete-orphan",
        backref="session",
    )


class ChatMessage(db.Model):
    """
    Represents a single message within a chat session.
    """

    id = db.Column(db.Integer, primary_key=True)
    chat_session_id = db.Column(
        db.Integer, db.ForeignKey("chat_session.id"), nullable=False, index=True
    )

    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Tag(db.Model):
    """
    Represents a tag that can be assigned to notes, optionally nested under a parent tag.
    """

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("tag.id"), nullable=True)
    parent = db.relationship("Tag", remote_side=[id], backref="children")

    def to_dict(self):
        """
        Convert the tag to a serializable dictionary.

        :return: A dict of the tag's key attributes.
        :rtype: dict
        """

        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "parent_id": self.parent_id,
        }


def get_tag_descendant_ids(root_ids):
    """
    Return root_ids plus all descendant tag ids.

    :param root_ids: A list of tag ids to find descendants for.
    :return: A set of tag ids including the root_ids and all their descendants.
    """

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
