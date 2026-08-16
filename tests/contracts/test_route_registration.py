def test_core_routes_remain_registered():
    from app import app

    assert "api" in app.blueprints

    routes = {rule.rule for rule in app.url_map.iter_rules()}
    expected = {
        "/",
        "/game",
        "/control",
        "/help",
        "/health",
        "/readyz",
        "/api/campaigns",
        "/api/campaigns/<campaign_id>",
        "/api/campaigns/<campaign_id>/session",
        "/api/sessions/<session_id>/player_state",
        "/api/sessions/<session_id>/chat_history",
        "/api/sessions/<session_id>/resume_data",
        "/api/sessions/<session_id>/recap",
        "/api/sessions/<session_id>/story_state",
        "/api/campaigns/<campaign_id>/rag/upload",
        "/api/campaigns/<campaign_id>/rag/query",
        "/api/propose",
        "/api/chat",
        "/api/narrate",
        "/api/saves/game/export",
        "/api/saves/game/import",
    }

    assert expected <= routes
