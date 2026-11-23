"""US23-US24: nível de habilidade, disponibilidade e sugestão de parceiros."""

import pytest

from tests.integration.test_courts_postgres import account

pytestmark = pytest.mark.integration


@pytest.fixture
def players(database_client):
    client = database_client
    users = {
        name: account(client, name, f"{name.lower()}@example.com")
        for name in ("Ana", "Bruno", "Carla", "Davi", "Elisa")
    }

    def profile(name, level, *slots):
        response = client.put(
            "/api/v1/players/me/profile",
            headers=users[name],
            json={
                "skill_level": level,
                "availability": [{"weekday": day, "period": period} for day, period in slots],
            },
        )
        assert response.status_code == 200, response.json()
        return response.json()["data"]

    def partners(name):
        return client.get("/api/v1/players/partners", headers=users[name])

    return client, users, profile, partners


def test_profile_starts_empty_and_is_replaced_on_save(players):
    client, users, profile, _ = players
    empty = client.get("/api/v1/players/me/profile", headers=users["Ana"]).json()["data"]
    assert empty == {"skill_level": None, "availability": []}

    saved = profile("Ana", "intermediate", (2, "evening"), (0, "morning"), (2, "afternoon"))
    assert saved["skill_level"] == "intermediate"
    # Ordenado por dia e período.
    assert saved["availability"] == [
        {"weekday": 0, "period": "morning"},
        {"weekday": 2, "period": "afternoon"},
        {"weekday": 2, "period": "evening"},
    ]

    replaced = profile("Ana", "advanced", (5, "morning"))
    assert replaced == {
        "skill_level": "advanced",
        "availability": [{"weekday": 5, "period": "morning"}],
    }
    reread = client.get("/api/v1/players/me/profile", headers=users["Ana"]).json()["data"]
    assert reread == replaced


def test_profile_validation(players):
    client, users, _, _ = players

    def put(body):
        return client.put("/api/v1/players/me/profile", headers=users["Ana"], json=body)

    assert put({"skill_level": "lenda", "availability": []}).status_code == 422
    bad_day = put(
        {"skill_level": "beginner", "availability": [{"weekday": 7, "period": "morning"}]}
    )
    assert bad_day.status_code == 422
    bad_period = put(
        {"skill_level": "beginner", "availability": [{"weekday": 1, "period": "madrugada"}]}
    )
    assert bad_period.status_code == 422
    repeated = put(
        {
            "skill_level": "beginner",
            "availability": [
                {"weekday": 1, "period": "morning"},
                {"weekday": 1, "period": "morning"},
            ],
        }
    )
    assert repeated.status_code == 422
    assert repeated.json()["errors"]["availability"] == [
        "Cada dia e período só pode aparecer uma vez."
    ]


def test_partners_need_own_level(players):
    _, _, _, partners = players
    response = partners("Ana")
    assert response.status_code == 409
    assert response.json() == {
        "message": "Informe seu nível de habilidade para encontrar parceiros.",
        "errors": {"skill_level": ["Informe seu nível de habilidade para encontrar parceiros."]},
    }


def test_partners_match_level_and_shared_availability(players):
    _, _, profile, partners = players
    profile("Ana", "intermediate", (1, "evening"), (3, "evening"), (5, "morning"))
    profile("Bruno", "intermediate", (1, "evening"))  # mesmo nível, 1 horário em comum
    profile("Carla", "advanced", (1, "evening"), (3, "evening"))  # nível vizinho, 2 em comum
    profile("Davi", "competitive", (1, "evening"), (3, "evening"), (5, "morning"))  # nível longe
    profile("Elisa", "beginner", (2, "morning"))  # nível vizinho, nada em comum

    response = partners("Ana")
    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["name"] for item in data] == ["Carla", "Bruno"]
    assert data[0] == {
        "id": data[0]["id"],
        "name": "Carla",
        "skill_level": "advanced",
        "shared_availability": [
            {"weekday": 1, "period": "evening"},
            {"weekday": 3, "period": "evening"},
        ],
    }
    assert "email" not in data[0]


def test_without_availability_partners_are_ranked_by_level(players):
    _, _, profile, partners = players
    profile("Ana", "intermediate")
    profile("Bruno", "advanced", (1, "morning"))
    profile("Carla", "intermediate")
    profile("Davi", "competitive")

    names = [item["name"] for item in partners("Ana").json()["data"]]
    assert names == ["Carla", "Bruno"]  # mesmo nível primeiro; competitivo fica de fora
