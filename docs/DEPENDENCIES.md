# Dependency registry (spec §46)

What we use, why, and what we refused to invent a worse copy of.

| Need | Choice | License / notes |
|---|---|---|
| HTTP | httpx | Existing. SSRF-safe wrapper in `app/engine/http.py`. |
| HTML parse | selectolax | Already in the creator engine; used by webintel. |
| Browser render | Playwright / Chromium | Logged-out only. No CAPTCHA or bot evasion. |
| Search | Serper / Brave / Google CSE | Official APIs. Never scrape Google HTML. |
| YouTube | Data API v3 + public pages | Official key optional; browser fallback. |
| Podcasts / Wikipedia / iTunes | Official public APIs | Keyless. |
| Web fetch cache | On-disk JSON | Redis deferred until a second process needs a shared cache. |
| Queue | FastAPI BackgroundTasks | Redis/RQ deferred; `events.py` is the hook. |
| Graph DB | SQL tables | Replaceable; engines talk to `app/omni/graph.py`. |
| Digital PDF text | pypdf | No OCR. Scanned pages stay INSUFFICIENT EVIDENCE. |
| DOCX text | python-docx | Already used for report export. |
| LLM router | optional OpenAI HTTP | Empty key = DESK only. Invented numbers rejected. |

Evaluated and **not** pulled in for this slice: Scrapy (our crawl is bounded and
policy-heavy already), trafilatura (selectolax + `_text` is enough for scored
pages), random GitHub “OSINT” kits (license/terms risk).
