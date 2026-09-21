"""

This module defines the subject, unit, and tag management routes for the
Notes-Recorder application.

"""

# Import required modules
import re
from flask import Response, request, jsonify, render_template

# Import core extensions and models
from core.extensions import app, db
from core.models import Subject, Unit, Tag, Note, get_tag_descendant_ids
from core.config import DEFAULT_PER_PAGE


@app.route("/manage")
def manage() -> str:
    """
    Render the Manage page for taxonomy and preferences (Step 8).

    :return: The rendered manage template.
    :rtype: str
    """

    return render_template(
        "pages/manage.html",
        counts={
            "notes": Note.query.count(),
            "subjects": Subject.query.count(),
            "units": Unit.query.count(),
            "tags": Tag.query.count(),
        },
        default_per_page=DEFAULT_PER_PAGE,
    )


@app.route("/api/subjects")
def api_subjects() -> Response:
    """
    List all subjects ordered by name.

    :return: A JSON response with the serialized subjects.
    :rtype: flask.Response
    """

    subjects = Subject.query.order_by(Subject.name).all()
    return jsonify({"subjects": [subject.to_dict() for subject in subjects]})


@app.route("/api/subjects", methods=["POST"])
def create_subject() -> Response:
    """
    Create a new subject.

    :return: A JSON response with the created subject, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "A subject name is required."}), 400

    if Subject.query.filter(db.func.lower(Subject.name) == name.lower()).first():
        return jsonify({"error": "That subject already exists."}), 400

    subject = Subject(name=name[:100])
    db.session.add(subject)
    db.session.commit()
    return jsonify({"subject": subject.to_dict()})


@app.route("/api/subjects/<int:subject_id>/delete", methods=["POST"])
def delete_subject(subject_id: int) -> Response:
    """
    Delete a subject.

    :param subject_id: ID of the subject.
    :type subject_id: int
    :return: A JSON response confirming the deletion, or 404 if not found.
    :rtype: flask.Response
    """

    subject = Subject.query.get_or_404(subject_id)
    db.session.delete(subject)
    db.session.commit()
    return jsonify({"message": "Subject deleted."})


@app.route("/api/units")
def api_units() -> Response:
    """
    List all units ordered by subject and unit name.

    :return: A JSON response with the serialized units.
    :rtype: flask.Response
    """

    units = Unit.query.join(Subject).order_by(Subject.name, Unit.name).all()
    return jsonify({"units": [unit.to_dict() for unit in units]})


@app.route("/api/units", methods=["POST"])
def create_unit() -> Response:
    """
    Create a new unit under a subject.

    :return: A JSON response with the created unit, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    subject_id = data.get("subject_id")
    name = (data.get("name") or "").strip()

    if not name or not str(subject_id).isdigit():
        return jsonify({"error": "Choose a subject and provide a unit name."}), 400

    subject = Subject.query.get(int(subject_id))
    if not subject:
        return jsonify({"error": "Subject not found."}), 404

    if Unit.query.filter_by(subject_id=subject.id, name=name).first():
        return jsonify({"error": "That unit already exists for this subject."}), 400

    unit = Unit(name=name[:100], subject_id=subject.id)
    db.session.add(unit)
    db.session.commit()
    return jsonify({"unit": unit.to_dict()})


@app.route("/api/units/<int:unit_id>/delete", methods=["POST"])
def delete_unit(unit_id: int) -> Response:
    """
    Delete a unit.

    :param unit_id: ID of the unit.
    :type unit_id: int
    :return: A JSON response confirming the deletion, or 404 if not found.
    :rtype: flask.Response
    """

    unit = Unit.query.get_or_404(unit_id)
    db.session.delete(unit)
    db.session.commit()
    return jsonify({"message": "Unit deleted."})


@app.route("/api/tags")
def api_tags() -> Response:
    """
    List all tags ordered by name.

    :return: A JSON response with the serialized tags.
    :rtype: flask.Response
    """

    tags = Tag.query.order_by(Tag.name).all()
    return jsonify({"tags": [tag.to_dict() for tag in tags]})


@app.route("/api/tags", methods=["POST"])
def create_tag() -> Response:
    """
    Create a new tag, optionally nested under a parent tag.

    :return: A JSON response with the created tag, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or "").strip()
    parent_id = data.get("parent_id")

    if not name or not re.match(r"^#[0-9a-fA-F]{6}$", color):
        return jsonify({"error": "A tag name and a valid hex color are required."}), 400

    if parent_id is not None:
        if not str(parent_id).isdigit():
            return jsonify({"error": "Invalid parent tag."}), 400
        parent_id = int(parent_id)
        Tag.query.get_or_404(parent_id)

    tag = Tag(name=name[:100], color=color, parent_id=parent_id)
    db.session.add(tag)
    db.session.commit()
    return jsonify({"tag": tag.to_dict()})


@app.route("/api/tags/<int:tag_id>", methods=["POST"])
def update_tag(tag_id: int) -> Response:
    """
    Update a tag's name and color.

    :param tag_id: ID of the tag.
    :type tag_id: int
    :return: A JSON response with the updated tag, or an error.
    :rtype: flask.Response
    """

    tag = Tag.query.get_or_404(tag_id)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or "").strip()

    if not name or not re.match(r"^#[0-9a-fA-F]{6}$", color):
        return jsonify({"error": "A tag name and a valid hex color are required."}), 400

    tag.name = name[:100]
    tag.color = color
    db.session.commit()
    return jsonify({"tag": tag.to_dict()})


@app.route("/api/tags/<int:tag_id>/delete", methods=["POST"])
def delete_tag(tag_id: int) -> Response:
    """
    Delete a tag and all of its descendant tags.

    :param tag_id: ID of the tag.
    :type tag_id: int
    :return: A JSON response confirming the deletion, or 404 if not found.
    :rtype: flask.Response
    """

    Tag.query.get_or_404(tag_id)
    ids_to_delete = get_tag_descendant_ids([tag_id])
    Tag.query.filter(Tag.id.in_(ids_to_delete)).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"message": "Tag deleted."})
