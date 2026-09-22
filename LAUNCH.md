# Launch checklist

Ordered so that nothing later depends on something earlier being skipped. The legal
section is not optional — it is the part that turns a working product into a sellable one.

---

## 1. Before you write any code (do this first)

- [ ] **Register the business.** Razorpay will not activate a live account without an
      entity, PAN and a business bank account. Sole proprietorship is enough to start.
- [ ] **GST.** Required above ₹20 lakh turnover (₹10 lakh in some states), but SaaS
      customers will ask for a GST invoice long before that. Register early if you intend
      to sell to companies.
- [ ] **Domain and email.** A billing product on a free email address does not convert.

## 2. Legal — the part that makes this sellable

You are building profiles of named individuals from public data. Under India's **DPDP Act
2023** that is personal data processing, and under **GDPR** too if any subject is in the
EU. None of this is exotic, but skipping it is what gets a product taken down.

- [ ] **Privacy policy**, published, covering: what you collect, the lawful basis
      (legitimate interest for B2B market intelligence), retention, and how to object.
- [ ] **Terms of service** covering acceptable use — explicitly forbid using reports to
      harass, stalk or target individuals.
- [ ] **A named grievance officer** with a working email. DPDP requires this.
- [ ] **A subject suppression list.** *This is still not built.* When a creator asks not
      to be profiled, you need a way to honour it. Build a `SuppressedSubject` table
      checked in `pipeline.collect` before any request goes out, plus a public request
      form. **Do not launch without it.**
- [ ] **Erasure process.** `Report.payload_json` is the single place a subject's data is
      stored — deletion is straightforward, but write down the procedure.
- [ ] **Never profile minors.** Several of these audiences are school students. You
      profile the *creator*, never their individual followers, and never anyone
      identifiably under 18.
- [ ] **Read `LEGAL.md`** on the browser tier. Reading a public page logged out is what
      any visitor does; automated rendering at commercial scale is a different posture.
      Take advice if you are selling this, and keep the rate limits where they are.

## 3. Razorpay

- [ ] Create the account, complete KYC (2–5 working days).
- [ ] Test mode first: `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` from Settings → API Keys.
- [ ] Webhook: `https://your-domain/billing/webhook`, secret into
      `RAZORPAY_WEBHOOK_SECRET`.
- [ ] Subscribe to these events: `subscription.activated`, `subscription.charged`,
      `subscription.halted`, `subscription.cancelled`, `subscription.paused`,
      `subscription.resumed`, `subscription.pending`, `subscription.completed`,
      `payment.failed`.
- [ ] Run one full test subscription end to end and confirm the org flips to `active` in
      `/admin`. **Entitlement only ever changes on a signature-verified webhook** — never
      on the browser redirect — so this test is the one that matters.
- [ ] Switch to live keys only after that passes.

## 4. Deploy

```bash
# on the server
git clone <your repo> creator-intel && cd creator-intel
cp .env.example .env      # fill in DOMAIN, POSTGRES_PASSWORD, ADMIN_TOKEN, Razorpay keys
docker compose -f docker-compose.prod.yml up -d --build
```

- [ ] Point your domain's A record at the server **before** first start, or Caddy's
      certificate challenge fails.
- [ ] `ADMIN_TOKEN` set to something from
      `python -c "import secrets;print(secrets.token_urlsafe(32))"`.
- [ ] **Restrict `/admin` by IP** in `Caddyfile` — the block is there, commented out.
      It is the highest-value target on the box.
- [ ] Confirm `https://your-domain/healthz` responds.
- [ ] Confirm `/admin` loads and the plan catalogue seeded.
- [ ] Set `MAX_CONCURRENCY` to match your RAM — see `HOSTING.md`.

## 5. Updating after launch

**SaaS:** `git pull && docker compose -f docker-compose.prod.yml up -d --build`. Schema
changes are additive today; introduce Alembic before your first destructive migration.

**Self-hosted customers:** publish the release in `/admin/releases` with a version, a
download URL and its SHA-256. Every instance picks it up on its next licence check-in.

```bash
# produce and hash a release artefact
zip -r creator-intel-2.2.0.zip creator-intel -x '*/data/*' '*/.env' '*/.venv/*'
sha256sum creator-intel-2.2.0.zip
```

The updater refuses any download whose hash does not match, backs up the current install
before unpacking, and never overwrites `.env` or `data/`. Mark a release **mandatory**
only for security fixes — it forces every customer to update.

## 6. Before taking real money

- [ ] Test the whole path on a second machine: signup → key → report → subscribe →
      webhook → quota → report again.
- [ ] Verify quota actually blocks. Consume the trial's three reports and confirm the
      block page appears.
- [ ] Verify a revoked key locks a customer out immediately.
- [ ] Confirm the nightly `pg_dump` produced a file in `./backups`, then **restore it into
      a scratch database**. An untested backup is not a backup.
- [ ] Decide your refund policy and put it in the ToS. Razorpay disputes go badly without
      one.
- [ ] Set up uptime monitoring on `/healthz`.

## 7. Pricing

Defaults ship at Solo ₹1,499, Agency ₹4,999, Self-hosted ₹9,999. All editable live in
`/admin/plans` with no deploy.

Two things to know before you change a price:

1. **Razorpay plans are immutable.** Editing a price here clears the stored plan id so a
   new Razorpay plan is created on the next subscription. Existing subscribers stay on
   the price they signed up at, which is the correct behaviour.
2. **Your marginal cost is per-report**, dominated by browser time and search queries.
   Roughly ₹1–3 per report at small scale. Price the tiers so the heaviest user on each
   still clears it.

## 8. What is deliberately not built yet

Being honest about the gaps so you can sequence them:

1. **Subject suppression list** — a legal requirement. Build this first.
2. **Alembic migrations** — tables auto-create today, which is fine until the first
   column you need to change.
3. **Real job queue** — background tasks handle a handful of concurrent reports. Move to
   RQ or Celery with Redis before you have paying customers running batches.
4. **Email** — signup shows the key on screen but sends nothing. Wire an SMTP or
   Resend/Postmark integration so customers can recover a lost key.
5. **Team seats** — plans declare a seat count; the enforcement is not written. Today one
   key equals one org.
6. **Usage-based overage** — quotas block rather than bill extra.
7. **Dunning** — a failed payment gets a 7-day grace, then blocks. No reminder emails.
