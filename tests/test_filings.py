"""Official filings — only when an identifier already exists. No valuation."""
from __future__ import annotations

import asyncio

from app.omni.filings import (cik_normalize, collect_filings, identifiers_from,
                              lei_normalize, parse_gleif, parse_sec_submissions)
from app.omni.identity import analyse_identity


def test_no_identifier_means_no_edgar():
    intel = identifiers_from([], {})
    assert intel == []


def test_unlabeled_digits_are_not_a_cik():
    html = "<html><body><p>Call 0000320193 for sales.</p></body></html>"
    intel = analyse_identity([("https://acme.example/", html)])
    kinds = {row.kind for row in intel.ids}
    assert "sec_cik" not in kinds


def test_labeled_cik_is_kept_unlabeled_is_not():
    html = "<html><body><p>SEC CIK 320193</p><p>Invoice 1234567890</p></body></html>"
    intel = analyse_identity([("https://acme.example/", html)])
    ciks = [row.value for row in intel.ids if row.kind == "sec_cik"]
    assert ciks == ["0000320193"]


def test_cin_pattern_is_not_an_mca_lookup():
    ids = identifiers_from([{"kind": "cin", "value": "U72200KA2018PTC123456"}])
    assert ids[0].kind == "cin"
    intel = asyncio.run(collect_filings(ids, {}))
    assert intel.assessed is True
    assert intel.records[0].kind == "mca"
    assert intel.records[0].status == "unavailable"
    blob = (intel.records[0].reason + intel.methodology).lower()
    assert "valuation" in blob
    assert "login" in blob or "captcha" in blob


def test_sec_parser_copies_forms_not_market_cap():
    payload = {
        "name": "Apple Inc.",
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "marketCap": 3_000_000_000_000,
        "valuation": 99,
        "filings": {"recent": {
            "form": ["10-K", "8-K"],
            "filingDate": ["2024-11-01", "2024-10-01"],
            "accessionNumber": ["0000320193-24-000123", "0000320193-24-000100"],
            "primaryDocument": ["aapl-20240928.htm", "8k.htm"],
        }},
    }
    rec = parse_sec_submissions(payload, "0000320193")
    assert rec is not None
    assert rec.name == "Apple Inc."
    assert rec.filings[0].form == "10-K"
    dumped = rec.model_dump()
    blob = str(dumped).lower()
    assert "3000000000000" not in blob
    assert "marketcap" not in blob
    assert "valuation" not in blob


def test_gleif_parser_is_name_and_status():
    payload = {
        "data": {"attributes": {"entity": {
            "legalName": {"name": "Example GmbH"},
            "status": "ACTIVE",
            "jurisdiction": "DE",
            "legalAddress": {"city": "Berlin", "country": "DE"},
            "marketCap": 1,
        }}}
    }
    rec = parse_gleif(payload, "529900T8BM49AURSDO55")
    assert rec is not None
    assert rec.name == "Example GmbH"
    assert rec.status == "ACTIVE"
    assert "Berlin" in rec.detail
    assert "1" not in rec.detail


def test_normalizers():
    assert cik_normalize("320193") == "0000320193"
    assert cik_normalize("not-a-cik") == ""
    assert lei_normalize("529900T8BM49AURSDO55") == "529900T8BM49AURSDO55"
    assert lei_normalize("short") == ""
