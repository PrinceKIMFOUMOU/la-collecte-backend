from fastapi.testclient import TestClient # type: ignore

from app.main import app


client = TestClient(app)


# =========================
# TESTS DE BASE
# =========================

def test_accueil():
    response = client.get("/")

    assert response.status_code == 200


def test_ressources_sans_token():
    response = client.get("/ressources")

    assert response.status_code == 401


def test_fichier_ressource_sans_token():
    response = client.get("/ressources/999999/fichier")

    assert response.status_code == 401


def test_ressources_token_invalide():
    response = client.get(
        "/ressources",
        headers={
            "Authorization": "Bearer faux_token_invalide"
        }
    )

    assert response.status_code == 401


# =========================
# TESTS ADMIN
# =========================

def test_admin_users_sans_token():
    response = client.get("/admin/users")

    assert response.status_code == 401


def test_admin_users_token_invalide():
    response = client.get(
        "/admin/users",
        headers={
            "Authorization": "Bearer faux_token_invalide"
        }
    )

    assert response.status_code == 401