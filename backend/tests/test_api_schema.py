def test_all_api_routes_have_resolvable_request_schemas():
    from src.api.main import app

    schema = app.openapi()
    assert "/context-memory" in schema["paths"]
    assert "patch" in schema["paths"]["/reminders/{reminder_id}"]
