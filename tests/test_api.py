import pytest
from fastapi.testclient import TestClient

from mission_planner.api import create_app
from mission_planner.fields import px4_sample_field


def _payload(battery: float, *, points: int = 4) -> dict:
    home, polygon = px4_sample_field()
    ring = [{"lat": point.lat, "lon": point.lon} for point in polygon]
    if points < 4:
        ring = ring[:points]
    return {
        "polygon": ring,
        "home": {"lat": home.lat, "lon": home.lon},
        "spacing_m": 20,
        "angle_deg": 90,
        "altitude_m": 25,
        "speed_m_s": 5,
        "margin_m": 0,
        "battery_percent": battery,
    }


@pytest.fixture
def client() -> tuple[TestClient, object]:
    app = create_app()
    return TestClient(app), app


def test_status_marks_the_energy_model_as_a_placeholder(client) -> None:
    http, _app = client
    body = http.get("/api/status").json()
    assert body["vehicle"] == "fake"
    assert body["energy_model"]["placeholder"] is True
    assert "not" in body["energy_model"]["note"].lower()
    assert len(body["sample_field"]["polygon"]) == 4
    assert "Zurich" in body["sample_field"]["note"]


def test_index_and_leaflet_are_served(client) -> None:
    http, _app = client
    page = http.get("/")
    assert page.status_code == 200
    assert "Survey grid" in page.text
    assert http.get("/static/styles.css").status_code == 200
    script = http.get("/static/vendor/leaflet.js")
    assert script.status_code == 200
    assert "Leaflet" in script.text[:200]


def test_preview_returns_a_launchable_path(client) -> None:
    http, app = client
    response = http.post("/api/preview", json=_payload(90))
    assert response.status_code == 200
    body = response.json()
    assert body["launchable"] is True
    assert body["waypoint_count"] >= 3
    assert body["waypoints"][0]["vehicle_action"] == "takeoff"
    assert body["distance_m"] > 0
    assert body["time_at_set_speed_s"] == pytest.approx(body["distance_m"] / 5)
    assert body["energy"]["placeholder"] is True
    assert body["geofence"]["ok"] is True
    assert app.state.system.action.armed is False


def test_preview_low_battery_keeps_the_path_and_blocks_launch(client) -> None:
    http, _app = client
    body = http.post("/api/preview", json=_payload(10)).json()
    assert body["launchable"] is False
    assert body["waypoint_count"] >= 3
    assert "start minimum" in body["reason"]
    assert body["energy"]["allowed"] is False


def test_launch_on_the_fake_vehicle_arms_and_starts(client) -> None:
    http, app = client
    response = http.post("/api/launch", json=_payload(90))
    assert response.status_code == 200
    body = response.json()
    assert body["started"] is True
    assert body["vehicle"] == "fake"
    assert body["stage"] == "started"
    assert app.state.system.action.armed is True
    assert app.state.system.mission.rtl_after_mission is True
    assert app.state.system.mission.started is True
    assert app.state.system.connected_address == "udpin://0.0.0.0:14540"


def test_launch_with_low_battery_does_not_arm(client) -> None:
    http, app = client
    body = http.post("/api/launch", json=_payload(10)).json()
    assert body["started"] is False
    assert "start minimum" in body["reason"]
    assert app.state.system.action.armed is False
    assert app.state.system.mission.uploaded is None


def test_rth_check_uses_the_fake_battery(client) -> None:
    http, app = client
    low = http.post("/api/rth-check", json={"battery_percent": 10}).json()
    assert low["action"] == "rtl"
    assert app.state.system.action.rtl_called is True

    high = http.post("/api/rth-check", json={"battery_percent": 80}).json()
    assert high["action"] == "continue"


def test_short_polygon_is_rejected_by_the_schema(client) -> None:
    http, _app = client
    response = http.post("/api/preview", json=_payload(80, points=2))
    assert response.status_code == 422
