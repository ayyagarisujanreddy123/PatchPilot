"""Separate landing/dashboard documents preserve API and static routing."""

import pytest


def test_landing_and_dashboard_have_distinct_page_shells(client):
    landing = client.get("/")
    dashboard = client.get("/dashboard")
    assert landing.status_code == 200
    assert 'data-page="landing"' in landing.text
    assert 'src="/static/js/landing.js"' in landing.text
    assert dashboard.status_code == 200
    assert 'data-page="dashboard"' in dashboard.text
    assert 'id="app-main"' in dashboard.text
    assert 'src="/static/js/main.js"' in dashboard.text
    assert landing.text != dashboard.text
    assert landing.headers["cache-control"] == "no-store"
    assert dashboard.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("query", ["", "?mock=1&scenario=rollback", "?mock=1&note=a%20b"])
def test_dashboard_slash_redirect_preserves_query(client, query):
    response = client.get("/dashboard/" + query, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard" + query


def test_page_routes_preserve_api_and_asset_namespaces(client):
    assert client.get("/api/health").json()["mode"] == "SIMULATION"
    for path in ("/static/js/main.js", "/static/styles.css", "/js/main.js", "/styles.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'data-page="landing"' not in response.text
    assert client.get("/dashboard/not-a-page").status_code == 404
