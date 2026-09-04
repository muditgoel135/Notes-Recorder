from core.extensions import db
from core.models import (
    ChatMessage,
    ChatSession,
    Note,
    Speaker,
    Subject,
    Tag,
    Unit,
    get_tag_descendant_ids,
)
from services.notes_query import init_database


def test_model_serializers_and_speaker_order(test_app):
    with test_app.app_context():
        note = Note(
            date="2026-09-03",
            time="10:00:00",
            start_time="10:00:00",
            end_time="10:05:00",
            subject="Physics",
        )
        subject = Subject(name="Math")
        db.session.add_all([note, subject])
        db.session.flush()
        unit = Unit(name="Algebra", subject_id=subject.id)
        tag = Tag(name="important", color="#123456")
        speaker = Speaker(
            note_id=note.id,
            order_index=0,
            label="Speaker 1",
            color="#4c78a8",
        )
        db.session.add_all([unit, tag, speaker])
        db.session.commit()

        assert note.speakers_by_order()[0] is speaker
        assert unit.to_dict() == {
            "id": unit.id,
            "name": "Algebra",
            "subject_id": subject.id,
        }
        assert subject.to_dict()["name"] == "Math"
        assert tag.to_dict()["parent_id"] is None
        assert speaker.to_dict()["label"] == "Speaker 1"


def test_tag_descendants_include_all_nested_children(test_app):
    with test_app.app_context():
        root = Tag(name="root", color="#111111")
        child = Tag(name="child", color="#222222", parent=root)
        grandchild = Tag(name="grandchild", color="#333333", parent=child)
        db.session.add(root)
        db.session.commit()
        assert get_tag_descendant_ids([root.id]) == {
            root.id,
            child.id,
            grandchild.id,
        }


def test_chat_relationships_and_repeated_database_initialization(test_app):
    with test_app.app_context():
        init_database()
        init_database()
        assert Subject.query.count() > 0

        session = ChatSession(title="Chat")
        db.session.add(session)
        db.session.flush()
        db.session.add(ChatMessage(session=session, role="user", content="hello"))
        db.session.commit()
        assert len(session.messages) == 1
