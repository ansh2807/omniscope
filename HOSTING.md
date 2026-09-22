# Hosting this in India — what it actually costs

Prices checked August 2026. Treat headline rates with suspicion: most "₹99/month" offers
are 2–4 year prepay, and USD-priced providers cost 2–5% more after Indian bank forex fees.

## What the workload actually needs

The browser tier is the constraint, not CPU. Each concurrent Chromium is roughly
**400 MB of RAM** and a report takes 30–90 seconds. Everything else — the inference
engine, rendering, Postgres — is trivial by comparison.

| Concurrent reports | RAM needed | Realistic throughput |
|---|---|---|
| 2 | 2 GB | ~60 reports/hour |
| 4 | 4 GB | ~120 reports/hour |
| 8 | 8 GB | ~240 reports/hour |

Set `MAX_CONCURRENCY` in `.env` to match. Over-provisioning it on a small box causes the
OOM killer to take out Postgres, which is a far worse failure than a queued job.

## The options, cheapest first

### 1. Oracle Cloud Always Free — Mumbai or Hyderabad · ₹0

Genuinely free forever, and the only ₹0 option with an Indian region.

- **Was** 4 ARM cores / 24 GB RAM. **Oracle halved this to 2 cores / 12 GB in June 2026**
  with no announcement, so plan for the new number.
- 200 GB block storage, 10 TB egress/month.
- ARM64 — Chromium and everything in this stack run fine on it.

**The catch, and it is a real one:** ARM capacity in Indian regions is frequently
exhausted, so you may wait days for a successful instance launch. Oracle has also
reclaimed idle Always Free instances in the past. **Do not run production billing on
this.** It is an excellent staging or pilot box.

### 2. Hostinger KVM — India datacentre · ₹250–450/month

- KVM 1: 1 vCPU, 4 GB RAM, 50 GB NVMe. ~₹373/month on the standard term.
- The ₹99 headline needs a 4-year prepay; month-to-month renews nearer ₹449.
- INR billing, no forex loss, Indian support hours.

**This is the sensible starting point for a real launch.** 4 GB comfortably runs the app,
Postgres and 3–4 concurrent browsers.

### 3. DigitalOcean Bangalore · $12/month ≈ ₹1,050

- 2 vCPU / 4 GB is the tier you want; the $4 droplet has 512 MB and cannot run Chromium.
- Excellent tooling, snapshots, managed Postgres available.
- USD billing — add ~3% forex.

Worth it when you want backups, monitoring and one-click restores without building them.

### 4. AWS Mumbai / Azure India · ₹1,500–3,000/month

Only if you need it for enterprise procurement or data-residency paperwork. For this
workload it is two to three times the price for no operational benefit.

## Recommended path

| Stage | Host | Cost |
|---|---|---|
| Build and pilot | Oracle Always Free, Mumbai | ₹0 |
| Launch, first ~50 customers | Hostinger KVM 2 India (4 GB) | ~₹450/mo |
| Growing | DigitalOcean Bangalore 8 GB + managed Postgres | ~₹3,500/mo |
| Scale | Split the browser workers onto their own box | as needed |

Total to go live is realistically **₹450–900/month** including a domain. The costs that
grow are search API queries and, eventually, residential proxies.

## The thing that will actually break first

**Datacentre IPs get rate-limited and blocked far faster than home IPs.** Instagram and
YouTube are both aggressive about this. A single VPS running hundreds of reports a day
will start seeing sign-in walls and challenges within weeks.

Three ways to handle it, in order of preference:

1. **Sell the self-hosted plan.** The customer runs it on their own connection, so their
   own IP reputation carries the load. This is the main commercial argument for that tier
   and it is why it is priced highest.
2. **Cache aggressively.** `CACHE_TTL_HOURS=24` already means re-running a creator inside
   a day costs zero requests. Raise it for popular subjects.
3. **Residential proxies** if you must scale hosted collection. Budget ₹800–4,000/month.
   Read `LEGAL.md` first — this changes your posture from "reading public pages" to
   "actively working around access controls", which is a materially different position.

## Sizing the database

Reports are files on disk, not rows. A single-creator report is ~85 KB of HTML plus
~55 KB of DOCX. A thousand reports is under 150 MB. Postgres holds only metadata and
stays in the tens of megabytes for a long time. Retention pruning is on by default.

## Backups

`docker-compose.prod.yml` runs a nightly `pg_dump` into `./backups`, keeping 14 days.
That covers accounts, subscriptions and licence keys — the data you genuinely cannot
recreate. Report files are regenerable, so they are not backed up by default.

Restore:

```bash
docker compose -f docker-compose.prod.yml exec -T db \
  psql -U ci creatorintel < backups/ci-2026-08-05.sql
```

**Test the restore before you need it.** An untested backup is a hope, not a backup.
