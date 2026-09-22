"""Evidence records — the audit trail behind every OMNISCOPE claim.

Every page the web engine reads becomes an `EvidenceRecord`: what URL was fetched,
when, the content hash, the collection method and what was read from it. Records are
stored inside the report payload (`Report.payload_json`), which keeps them inside the
existing retention, deletion and erasure paths.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.engine.http import Fetched


class EvidenceRecord(BaseModel):
    claim: str                       # what this source supports, in one line
    source_url: str
    method: str = "http_get"         # http_get | browser_render | official_api | search_api
    collected_at: str = ""
    content_sha256: str | None = None
    from_cache: bool = False
    note: str = ""


class EvidenceLog(BaseModel):
    records: list[EvidenceRecord] = Field(default_factory=list)

    def add_fetch(self, fetched: Fetched, claim: str, *, method: str = "http_get",
                  note: str = "") -> EvidenceRecord:
        rec = EvidenceRecord(
            claim=claim,
            source_url=fetched.final_url or fetched.url,
            method=method,
            collected_at=fetched.fetched_at or datetime.now(timezone.utc).isoformat(),
            content_sha256=fetched.content_sha256
            or (hashlib.sha256(fetched.text.encode()).hexdigest() if fetched.text else None),
            from_cache=fetched.from_cache,
            note=note,
        )
        self.records.append(rec)
        return rec

    def add(self, claim: str, source_url: str, *, method: str = "derived",
            note: str = "") -> EvidenceRecord:
        rec = EvidenceRecord(claim=claim, source_url=source_url, method=method,
                             collected_at=datetime.now(timezone.utc).isoformat(),
                             note=note)
        self.records.append(rec)
        return rec
