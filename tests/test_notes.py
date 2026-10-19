from fastapi.testclient import TestClient


def test_create_and_list_notes(client: TestClient) -> None:
    created = client.post("/notes", json={"text": "hello"})
    assert created.status_code == 201

    listed = client.get("/notes")
    assert [n["text"] for n in listed.json()] == ["hello"]
