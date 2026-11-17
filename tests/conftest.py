import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}

# Fictional demo customers (see app/seed.py)
AHMED = {"cnic": "35202-1234567-1", "dob": "15 March 1990"}   # debit 4321 active, credit 9876 inactive
FATIMA = {"cnic": "42101-7654321-8", "dob": "2 November 1985"}  # one active debit 5544
USMAN = {"cnic": "61101-1122334-5", "dob": "21 July 2000"}      # one inactive card 3002


def make_settings(tmp_path, **overrides):
    base = dict(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        api_key=API_KEY,
        cnic_pepper="test-pepper",
        seed_demo_data=True,
        ring_timeout_seconds=20,
        sweep_interval_seconds=3600,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def make_client(tmp_path):
    clients = []

    def _make(**overrides):
        app = create_app(make_settings(tmp_path, **overrides))
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def db(client):
    with client.app.state.session_factory() as session:
        yield session


class Caller:
    """Test helper simulating one phone call."""

    def __init__(self, client, phone="+923001234567"):
        self.client = client
        r = client.post("/api/v1/calls", json={"caller_phone": phone})
        assert r.status_code == 201, r.text
        self.start = r.json()
        self.id = self.start["call_id"]
        self.last = self.start

    def say(self, text):
        r = self.client.post(f"/api/v1/calls/{self.id}/message", json={"text": text})
        assert r.status_code == 200, r.text
        self.last = r.json()
        return self.last

    def verify(self, who):
        self.say(who["cnic"])
        return self.say(who["dob"])

    def info(self):
        return self.client.get(f"/api/v1/calls/{self.id}").json()


@pytest.fixture
def caller(client):
    return Caller(client)


@pytest.fixture
def new_caller(client):
    return lambda phone="+923001234567": Caller(client, phone)
