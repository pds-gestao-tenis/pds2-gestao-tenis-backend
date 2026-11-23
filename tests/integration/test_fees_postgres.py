"""US19-US22: taxas dos membros, pagamentos e pendências."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.integration.test_courts_postgres import account

pytestmark = pytest.mark.integration


def club_today() -> date:
    # "Hoje" no fuso do clube, como a API decide o que está atrasado.
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


@pytest.fixture
def club(member_admin_client):
    """Admin, a conta de jogador do Bruno e os cadastros de membro do Bruno e da Carla."""
    client, admin = member_admin_client
    bruno = account(client, "Bruno", "bruno@example.com")

    def member(name, email):
        response = client.post(
            "/api/v1/members", headers=admin, json={"name": name, "email": email}
        )
        assert response.status_code == 201
        return response.json()["data"]["id"]

    ids = {
        "bruno": member("Bruno Lima", "bruno@example.com"),
        "carla": member("Carla Dias", "carla@example.com"),
    }

    def fee(member_id, description="Mensalidade", amount="150.00", due=None):
        due = due or (club_today() + timedelta(days=10)).isoformat()
        response = client.post(
            "/api/v1/fees",
            headers=admin,
            json={
                "member_id": member_id,
                "description": description,
                "amount": amount,
                "due_date": due,
            },
        )
        assert response.status_code == 201, response.json()
        return response.json()["data"]

    return client, admin, bruno, ids, fee


def test_admin_creates_fee_and_registers_payment(club):
    client, admin, _, ids, fee = club
    created = fee(ids["bruno"], "Mensalidade de dezembro", "150.5")
    assert created["member"]["name"] == "Bruno Lima"
    assert created["amount"] == 150.5
    assert created["status"] == "pending"
    assert created["overdue"] is False
    assert created["paid_at"] is None

    paid = client.post(
        f"/api/v1/fees/{created['id']}/payment", headers=admin, json={"method": "cash"}
    )
    assert paid.status_code == 200
    body = paid.json()["data"]
    assert body["status"] == "paid"
    assert body["payment_method"] == "cash"
    assert body["paid_via"] == "admin"
    assert body["paid_at"]

    again = client.post(
        f"/api/v1/fees/{created['id']}/payment", headers=admin, json={"method": "pix"}
    )
    assert again.status_code == 409
    assert again.json()["message"] == "Esta taxa já foi paga."


def test_fee_validation(club):
    client, admin, _, ids, _ = club
    invalid = client.post(
        "/api/v1/fees",
        headers=admin,
        json={"member_id": ids["bruno"], "description": " ", "amount": "0", "due_date": "ontem"},
    )
    assert invalid.status_code == 422
    assert set(invalid.json()["errors"]) == {"description", "amount", "due_date"}

    unknown = client.post(
        "/api/v1/fees",
        headers=admin,
        json={"member_id": 999999, "description": "x", "amount": "10", "due_date": "2030-01-01"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["message"] == "Membro não encontrado."

    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    created = client.post(
        "/api/v1/fees",
        headers=admin,
        json={
            "member_id": ids["bruno"],
            "description": "x",
            "amount": "10",
            "due_date": "2030-01-01",
        },
    ).json()["data"]
    response = client.post(
        f"/api/v1/fees/{created['id']}/payment",
        headers=admin,
        json={"method": "cash", "paid_at": future},
    )
    assert response.status_code == 422
    assert "paid_at" in response.json()["errors"]


def test_only_pending_fees_can_be_edited_or_deleted(club):
    client, admin, _, ids, fee = club
    pending = fee(ids["bruno"])
    edited = client.patch(
        f"/api/v1/fees/{pending['id']}",
        headers=admin,
        json={"amount": "175", "description": "Anuidade"},
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["amount"] == 175.0
    assert edited.json()["data"]["description"] == "Anuidade"

    client.post(f"/api/v1/fees/{pending['id']}/payment", headers=admin, json={"method": "pix"})
    assert (
        client.patch(
            f"/api/v1/fees/{pending['id']}", headers=admin, json={"amount": "1"}
        ).status_code
        == 409
    )
    assert client.delete(f"/api/v1/fees/{pending['id']}", headers=admin).status_code == 409

    other = fee(ids["bruno"])
    assert client.delete(f"/api/v1/fees/{other['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/fees/{other['id']}", headers=admin).status_code == 404


def test_listing_filters_and_overdue(club):
    client, admin, _, ids, fee = club
    late = fee(ids["carla"], "Atrasada", due=(club_today() - timedelta(days=5)).isoformat())
    fee(ids["bruno"], "Futura")
    paid = fee(ids["bruno"], "Paga", due=(club_today() - timedelta(days=9)).isoformat())
    client.post(f"/api/v1/fees/{paid['id']}/payment", headers=admin, json={"method": "card"})

    def names(query=""):
        response = client.get(f"/api/v1/fees{query}", headers=admin)
        assert response.status_code == 200
        return [item["description"] for item in response.json()["data"]]

    assert names() == ["Paga", "Atrasada", "Futura"]
    assert names("?status=pending") == ["Atrasada", "Futura"]
    assert names(f"?member_id={ids['bruno']}") == ["Paga", "Futura"]
    assert names("?overdue=true") == ["Atrasada"]
    listed = client.get("/api/v1/fees?overdue=true", headers=admin).json()["data"][0]
    assert listed["id"] == late["id"]
    assert listed["overdue"] is True


def test_admin_sees_who_has_pending_payments(club):
    client, admin, _, ids, fee = club
    fee(ids["bruno"], "Mensalidade", "100", due=(club_today() + timedelta(days=3)).isoformat())
    fee(ids["carla"], "Mensalidade", "100", due=(club_today() - timedelta(days=20)).isoformat())
    fee(ids["carla"], "Torneio", "50.25", due=(club_today() + timedelta(days=1)).isoformat())
    paid = fee(ids["bruno"], "Paga")
    client.post(f"/api/v1/fees/{paid['id']}/payment", headers=admin, json={"method": "cash"})

    response = client.get("/api/v1/fees/pending-members", headers=admin)
    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["member"]["name"] for item in data] == ["Carla Dias", "Bruno Lima"]
    assert data[0] == {
        "member": {"id": ids["carla"], "name": "Carla Dias", "email": "carla@example.com"},
        "pending_count": 2,
        "pending_total": 150.25,
        "overdue_count": 1,
        "oldest_due_date": (club_today() - timedelta(days=20)).isoformat(),
    }
    assert data[1]["pending_count"] == 1
    assert data[1]["overdue_count"] == 0


def test_player_sees_own_fees_and_pays(club):
    client, admin, bruno, ids, fee = club
    mine = fee(ids["bruno"], "Mensalidade", "120")
    late = fee(ids["bruno"], "Anuidade", "300", due=(club_today() - timedelta(days=1)).isoformat())
    fee(ids["carla"], "Da Carla", "999")
    received = fee(ids["bruno"], "Torneio", "40")
    client.post(f"/api/v1/fees/{received['id']}/payment", headers=admin, json={"method": "cash"})

    response = client.get("/api/v1/fees/mine", headers=bruno)
    assert response.status_code == 200
    body = response.json()
    assert body["member"]["name"] == "Bruno Lima"
    assert [item["description"] for item in body["data"]] == ["Anuidade", "Mensalidade", "Torneio"]
    assert body["summary"] == {"pending_total": 420.0, "paid_total": 40.0, "overdue_count": 1}
    assert body["data"][0]["id"] == late["id"]

    paid = client.post(f"/api/v1/fees/mine/{mine['id']}/pay", headers=bruno, json={"method": "pix"})
    assert paid.status_code == 200
    assert paid.json()["data"]["status"] == "paid"
    assert paid.json()["data"]["paid_via"] == "online"
    assert paid.json()["data"]["payment_method"] == "pix"
    again = client.post(
        f"/api/v1/fees/mine/{mine['id']}/pay", headers=bruno, json={"method": "card"}
    )
    assert again.status_code == 409

    summary = client.get("/api/v1/fees/mine", headers=bruno).json()["summary"]
    assert summary == {"pending_total": 300.0, "paid_total": 160.0, "overdue_count": 1}


def test_player_cannot_pay_or_manage_other_fees(club):
    client, _, bruno, ids, fee = club
    carla_fee = fee(ids["carla"])
    response = client.post(
        f"/api/v1/fees/mine/{carla_fee['id']}/pay", headers=bruno, json={"method": "pix"}
    )
    assert response.status_code == 404
    assert response.json()["message"] == "Taxa não encontrada."
    assert (
        client.post(
            f"/api/v1/fees/mine/{carla_fee['id']}/pay", headers=bruno, json={"method": "cash"}
        ).status_code
        == 422
    )

    assert client.get("/api/v1/fees", headers=bruno).status_code == 403
    assert client.get("/api/v1/fees/pending-members", headers=bruno).status_code == 403
    assert (
        client.post(
            f"/api/v1/fees/{carla_fee['id']}/payment", headers=bruno, json={"method": "cash"}
        ).status_code
        == 403
    )


def test_account_without_member_record_sees_empty_list(club):
    client = club[0]
    dani = account(client, "Dani", "dani@example.com")
    body = client.get("/api/v1/fees/mine", headers=dani).json()
    assert body == {
        "member": None,
        "data": [],
        "summary": {"pending_total": 0.0, "paid_total": 0.0, "overdue_count": 0},
    }
