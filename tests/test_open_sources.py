import asyncio

from app.omni import open_sources as src
from app.omni.news import from_hits, scan
from app.schemas import SearchHit


class _Resp:
    def __init__(self, text, ok=True):
        self.text = text
        self.ok = ok


def test_wayback_reads_cdx_and_availability(monkeypatch):
    async def fake_fetch(url, **_kwargs):
        if "cdx/search" in url:
            return _Resp('[["timestamp"],["19970115000000"]]')
        return _Resp(
            '{"archived_snapshots":{"closest":{"timestamp":"20240102030405",'
            '"url":"https://web.archive.org/web/20240102030405/https://acme.com/"}}}')

    monkeypatch.setattr(src, "fetch", fake_fetch)
    intel = asyncio.run(src.wayback("acme.com"))
    assert intel.assessed is True
    assert intel.first_capture == "1997-01-15"
    assert intel.last_capture == "2024-01-02"
    assert "web.archive.org" in intel.last_url


def test_hacker_news_keeps_only_token_matches(monkeypatch):
    async def fake_fetch(_url, **_kwargs):
        return _Resp('{"hits":['
                     '{"title":"Acme raises a round","url":"https://news.example/acme",'
                     '"points":12,"num_comments":3,"created_at":"2026-01-02",'
                     '"objectID":"1"},'
                     '{"title":"Unrelated picnic","url":"https://other.example/x",'
                     '"objectID":"2"}]}')

    monkeypatch.setattr(src, "fetch", fake_fetch)
    hits = asyncio.run(src.hacker_news("Acme", "acme.com"))
    assert len(hits) == 1
    assert hits[0].provider == "hackernews"
    assert "12 points" in hits[0].snippet


def test_datamuse_and_cctld_country(monkeypatch):
    async def fake_fetch(url, **_kwargs):
        if "datamuse" in url:
            return _Resp('[{"word":"crm","score":100},{"word":"saas","score":80}]')
        return _Resp('[{"name":{"common":"India"},"region":"Asia","capital":["New Delhi"]}]')

    monkeypatch.setattr(src, "fetch", fake_fetch)
    words = asyncio.run(src.related_words("customer relationship"))
    assert words.assessed is True
    assert words.rows[0].word == "crm"
    country = asyncio.run(src.country_for_domain("shop.example.in"))
    assert country.assessed is True
    assert country.name == "India"
    generic = asyncio.run(src.country_for_domain("acme.com"))
    assert generic.assessed is False


def test_news_falls_back_to_hacker_news(monkeypatch):
    class _Empty:
        async def get_news(self, _query, limit=8):
            return []

    async def fake_hn(name, domain, limit=8):
        return [SearchHit(query="acme", title="Acme sued over ads",
                          url="https://news.ycombinator.com/item?id=1",
                          snippet="lawsuit filed", provider="hackernews")]

    import app.providers.search as search_mod
    monkeypatch.setattr(search_mod, "search_provider", lambda: _Empty())
    monkeypatch.setattr("app.omni.news.hacker_news", fake_hn)

    intel = asyncio.run(scan("Acme", "acme.com"))
    assert intel.assessed is True
    assert intel.items[0].narrative == "crisis"
    assert "Hacker News" in intel.methodology


def test_from_hits_empty_stays_unavailable():
    empty = from_hits([], "acme")
    assert empty.assessed is False
