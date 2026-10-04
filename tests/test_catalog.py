from kie_mcp.catalog import CATALOG, get_catalog_entry, search_catalog


def test_catalog_contains_official_docs() -> None:
    assert len(CATALOG) >= 200
    results = search_catalog("nano banana 2")
    assert results
    assert "nanobanana2" in results[0]["url"]


def test_catalog_lookup_by_slug() -> None:
    entry = get_catalog_entry("common-api--get-account-credits")
    assert entry is not None
    assert entry["kind"] == "query"
