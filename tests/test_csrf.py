"""

Tests for the cross-origin CSRF guard.

"""

from core.extensions import app

from services.csrf import is_same_origin, reject_cross_origin_state_changes


def test_is_same_origin_matches_host():
    with app.test_request_context("/", headers={"Host": "localhost:5000"}):
        assert is_same_origin("http://localhost:5000") is True
        assert is_same_origin("http://localhost:5000/some/path") is True
        assert is_same_origin("http://evil.example.com") is False
        assert is_same_origin("") is False
        assert is_same_origin("null") is False


def test_reject_cross_origin_post(test_app):
    test_app.before_request(reject_cross_origin_state_changes)

    @test_app.route("/echo", methods=["POST"])
    def echo():
        return "ok"

    client = test_app.test_client()
    forged = client.post("/echo", headers={"Origin": "http://evil.example.com"})
    assert forged.status_code == 403

    legit = client.post("/echo", headers={"Origin": "http://localhost"})
    assert legit.status_code == 200

    headerless = client.post("/echo")
    assert headerless.status_code == 200


def test_reject_cross_origin_referer(test_app):
    test_app.before_request(reject_cross_origin_state_changes)

    @test_app.route("/echo", methods=["POST"])
    def echo():
        return "ok"

    client = test_app.test_client()
    forged = client.post(
        "/echo", headers={"Referer": "http://evil.example.com/attack.html"}
    )
    assert forged.status_code == 403


def test_read_methods_not_blocked(test_app):
    test_app.before_request(reject_cross_origin_state_changes)

    @test_app.route("/ping")
    def ping():
        return "pong"

    client = test_app.test_client()
    response = client.get("/ping", headers={"Origin": "http://evil.example.com"})
    assert response.status_code == 200
