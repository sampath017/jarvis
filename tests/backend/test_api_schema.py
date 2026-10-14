def test_all_api_routes_have_resolvable_request_schemas():
    from src.api.main import app

    schema = app.openapi()
    assert "post" in schema["paths"]["/context-events"]
    assert "post" in schema["paths"]["/commands/stream"]
    assert "post" in schema["paths"]["/mobile/parse-file"]
    assert "post" in schema["paths"]["/drive-index/files/{file_id}"]
    assert "/sync/push" not in schema["paths"]
    assert "/reminders/{reminder_id}" not in schema["paths"]
