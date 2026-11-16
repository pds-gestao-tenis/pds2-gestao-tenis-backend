import pytest

pytestmark = pytest.mark.integration

COURT = {
    "name": "Quadra Central",
    "address": "Rua das Palmeiras, 100",
    "size_m2": 260.76,
    "max_players": 4,
    "hourly_price": "120.50",
    "surface": "clay",
    "covered": False,
}


def account(client, name, email):
    password = "SenhaSegura123"
    created = client.post(
        "/api/v1/auth/register",
        json={
            "name": name,
            "email": email,
            "password": password,
            "password_confirmation": password,
        },
    )
    assert created.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_court_lifecycle(member_admin_client):
    client, admin = member_admin_client
    created = client.post("/api/v1/courts", headers=admin, json=COURT)
    assert created.status_code == 201
    court = created.json()["data"]
    assert court["size_m2"] == 260.76
    assert court["hourly_price"] == 120.5
    assert court["max_players"] == 4
    assert (court["surface"], court["covered"], court["maintenance"]) == ("clay", False, [])
    path = f"/api/v1/courts/{court['id']}"

    changed = client.patch(
        path,
        headers=admin,
        json={"hourly_price": 150, "name": " Quadra 1 ", "surface": "hard", "covered": True},
    )
    assert changed.status_code == 200
    assert (changed.json()["data"]["surface"], changed.json()["data"]["covered"]) == ("hard", True)
    assert changed.json()["data"]["name"] == "Quadra 1"
    assert changed.json()["data"]["hourly_price"] == 150
    assert changed.json()["data"]["address"] == COURT["address"]

    listing = client.get("/api/v1/courts?q=quadra", headers=admin)
    assert listing.json()["meta"]["total"] == 1
    assert client.delete(path, headers=admin).status_code == 204
    assert client.get(path, headers=admin).status_code == 404


def test_court_name_is_unique(member_admin_client):
    client, admin = member_admin_client
    assert client.post("/api/v1/courts", headers=admin, json=COURT).status_code == 201
    duplicate = client.post(
        "/api/v1/courts", headers=admin, json={**COURT, "name": COURT["name"].upper()}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["errors"] == {"name": ["Já existe uma quadra com este nome."]}


def test_any_account_reads_courts_but_only_admin_changes_them(member_admin_client):
    client, admin = member_admin_client
    court = client.post("/api/v1/courts", headers=admin, json=COURT).json()["data"]
    user = account(client, "Bruno", "bruno@example.com")
    path = f"/api/v1/courts/{court['id']}"
    assert client.get("/api/v1/courts", headers=user).status_code == 200
    assert client.get(path, headers=user).status_code == 200
    assert client.post("/api/v1/courts", headers=user, json=COURT).status_code == 403
    assert client.patch(path, headers=user, json={"name": "X"}).status_code == 403
    assert client.delete(path, headers=user).status_code == 403
    assert client.get("/api/v1/courts").status_code == 401


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"surface": "carpet"}, "surface"),
        ({"surface": None}, "surface"),
        ({"covered": "sim"}, "covered"),
        ({"covered": None}, "covered"),
    ],
)
def test_rejects_invalid_surface_or_covered(member_admin_client, overrides, field):
    client, admin = member_admin_client
    response = client.post("/api/v1/courts", headers=admin, json={**COURT, **overrides})
    assert response.status_code == 422
    assert field in response.json()["errors"]
    if overrides == {"surface": "carpet"}:
        assert response.json()["errors"]["surface"] == [
            "Escolha um piso válido: clay, hard, grass ou synthetic."
        ]


def test_create_requires_surface_and_covered(member_admin_client):
    client, admin = member_admin_client
    payload = {key: value for key, value in COURT.items() if key not in {"surface", "covered"}}
    response = client.post("/api/v1/courts", headers=admin, json=payload)
    assert response.status_code == 422
    assert set(response.json()["errors"]) == {"surface", "covered"}
