# Compliance posture

This is the part that decides whether you can sell this product. Read it before changing
anything in `app/engine/http.py` or the collectors.

## The browser tier, and why it is defensible

The engine can render public pages in a headless browser. This exists because Instagram
and YouTube build their pages with JavaScript, so a follower count or a comment thread is
visible to any visitor but absent from the raw HTML. Rendering the page is what a
visitor's browser does.

What the browser tier does **not** do, enforced in `app/engine/collectors/browser.py`:

* **Never logs in.** The browser context is created with no `storage_state`, no cookies
  and no credentials. It sees exactly what a signed-out visitor sees.
* **Never bypasses a login wall.** Instagram's post grid stays behind its sign-in prompt.
  The engine reads the profile header and then asks a human for the rest.
* **Never solves a CAPTCHA or evades bot detection.** If a challenge appears, the run
  stops and records it.
* **Never rotates proxies or identities.** One User-Agent, one identity, rate-limited.
* **Declines cookie banners** by choosing the most privacy-preserving option available.

Two honest caveats you should weigh before launching commercially:

1. **Platform terms.** Reading a public page logged out is what every visitor does, but
   automated rendering at volume is a different posture from a single human visit. Both
   YouTube and Instagram terms restrict automated access. If you are operating at scale
   or selling this as a service, take legal advice and consider the official APIs and
   licensed data providers for the platforms that offer them — the engine already
   prefers the YouTube Data API when a key is present.
2. **Rate limiting is your protection.** `PER_HOST_DELAY` and `MAX_CONCURRENCY` are not
   decorative. Do not raise them to make reports faster.

Set `BROWSER_MODE=off` to disable the tier entirely and run on official APIs plus plain
HTTP only.

## What the engine does

| Behaviour | Status |
|---|---|
| Reads pages a creator published publicly | Yes |
| Renders those pages logged out when they need JavaScript | Yes, when enabled |
| Honours `robots.txt` on general web requests | Yes — `RESPECT_ROBOTS=true` |
| Per-host rate limiting and on-disk caching | Yes |
| Identifies itself with a real User-Agent and contact URL | Yes |
| Uses official APIs where they exist (YouTube Data API, iTunes lookup) | Yes |
| Uses licensed search APIs for the discovery layer | Yes |

## What the engine deliberately does not do

* **No login-wall bypass.** No stored session cookies, no credential replay, no
  authenticated scraping of Instagram or LinkedIn. The browser tier is logged out by
  construction — see above.
* **No CAPTCHA or bot-detection evasion.**
* **No proxy rotation to defeat rate limits.**
* **No search-engine HTML scraping.** Search goes through a paid API or not at all.
* **No fabricated analytics.** If a number is not obtainable it is labelled
  `UNAVAILABLE`, not estimated into existence.

When data sits behind authentication, the job pauses and asks a human analyst to supply
it. That is a deliberate product decision, not a technical limitation, and it is what
keeps this shippable.

## Things to get right before you launch

1. **Set a real `USER_AGENT`** with a URL explaining what the bot is and how to block it.
   Publish that page.
2. **Never ship with `RESPECT_ROBOTS=false`.** It exists for local debugging against your
   own properties.
3. **Personal data.** Follower counts and public bios are public, but a compiled dossier
   on a named individual is personal data under India's DPDP Act and the GDPR when EU
   subjects are involved. Before launch you need: a privacy notice, a lawful basis
   (legitimate interest is the usual one for B2B market intelligence), a retention policy,
   and a working process for erasure and objection requests. Reports (including
   `Report.payload_json`) are deleted after 24 hours by default.
4. **Do not profile minors.** Several of these audiences are school students. Profile the
   *creator*, never their individual followers, and never collect data on identifiable
   under-18s.
5. **Third-party API terms.** YouTube Data API has its own ToS (notably around storing and
   displaying data). Read it. The same goes for whichever search provider you license.
6. **Instagram provider adapters.** If you enable `IG_PROVIDER`, you are relying on that
   vendor's compliance, not your own. Get their ToS in writing and keep the contract.
7. **Report disclaimers.** The renderer already prints the observed/estimated/unavailable
   key and a compliance note on every report. Keep it there — it is what makes the output
   defensible to a subject who reads their own profile.

## If a creator objects

Have a stated process: verify identity, delete the stored reports and cache entries for
that subject, and add the handle to a suppression list checked in `pipeline.collect`.
That block list is not implemented yet — it is the first thing to build before launch.
