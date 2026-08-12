"""

CSRF protection helpers for state-changing routes.

"""

# Import required modules
from urllib.parse import urlparse
from flask import jsonify, request

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_same_origin(url):
    """
    Whether a URL's scheme and host match the current request's host.

    :param url: A fully-qualified URL from an Origin or Referer header.
    :type url: str
    :return: True when the URL belongs to the current host.
    :rtype: bool
    """

    parsed = urlparse(url)
    return bool(parsed.scheme and parsed.netloc) and parsed.netloc == request.host


def reject_cross_origin_state_changes():
    """
    Reject state-changing requests that arrive from another origin.

    Browsers attach an Origin (and typically Referer) header on cross-site
    requests; when it names a different host the request is CSRF-forged, so it
    is rejected. Clients that send no such header (curl, internal tooling) are
    allowed, since their origin cannot be verified.

    :return: A 403 JSON response for forged requests, otherwise None.
    :rtype: flask.Response or None
    """

    if request.method not in STATE_CHANGING_METHODS:
        return None

    origin = request.headers.get("Origin")
    if origin is not None:
        if not is_same_origin(origin):
            return jsonify({"error": "Cross-origin request rejected."}), 403
        return None

    referrer = request.headers.get("Referer")
    if referrer is not None and not is_same_origin(referrer):
        return jsonify({"error": "Cross-origin request rejected."}), 403

    return None
