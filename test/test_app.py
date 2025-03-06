import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config.update(
        {
            "TESTING": True,
        }
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_index(client):
    response = client.get("/")
    assert response.status_code == 200
