# NinjaTrade — Organic Growth Ideas

**Audience**: futures traders who self-host their own tools. Narrow, technical, skeptical of SaaS.

**Goal**: Personal tool first — marketing only matters *if* you decide to open-source it. If you don't, skip this whole document.

---

## Current Status: No Marketing Needed

NinjaTrade is a personal self-hosted tool. There's nothing to market until/unless you decide to share the code publicly. Any effort spent on growth before that is wasted.

---

## If/When You Open-Source It

Self-hosting is **the entire pitch** for this brand — it's what differentiates NinjaTrade from every SaaS trading journal in the space. Lean into it hard.

### 1. GitHub README as the primary growth asset
The README is the landing page. Cover:
- **Why self-hosted** — no broker API keys in a third-party SaaS, your trade data never leaves your machine, no subscription, no account
- One-command install (`docker compose up` or equivalent)
- Screenshots of the dashboard and analytics
- Clear data source story (NinjaTrader export? file watch? etc.)
- Privacy-first framing — this is a huge draw for futures traders who are paranoid (rightfully so) about their trade data

A great README on a useful tool ranks in Google on its own and gets shared in communities for free.

### 2. Futures trading subreddits
- **r/FuturesTrading** — primary target
- **r/Daytrading** — secondary
- **r/algotrading** — if you build any programmatic features

One honest post when the code is stable: "I built a self-hosted futures trading journal because I didn't want my trades in someone else's database — here's the repo, feedback welcome." That's it. Don't repost, don't spam — one post, one time, genuine.

### 3. Hacker News "Show HN" — fire once
"Show HN: self-hosted futures trading journal with automatic trade capture." HN loves self-hosted alternatives to SaaS. Only fire this once — time it for when the project is polished and documented.

### 4. Awesome-lists on GitHub
Submit to:
- awesome-selfhosted
- awesome-trading (and any futures-specific variants)
- awesome-quant (if there's an analytics angle)

Free distribution, permanent backlinks, and exactly the audience you want.

### 5. NinjaTrader community forums
If the tool integrates with or exports from NinjaTrader, post in their forums once the integration is solid. Highly targeted audience.

---

## Email Hook (only if you add a splash page)

> "Notify me when the code is released."

That's it. A waitlist form. Don't try to build a newsletter for a personal tool — it'll feel forced and the audience will smell it.

---

## Skip Entirely

- Social media marketing of any kind
- Paid distribution
- Content marketing / blog posts
- YouTube tutorials until there's a v1.0 worth recording

---

## First-Month Priorities (only if going public)

1. Polish the README until it's the best documentation in the futures-tooling space
2. Dockerize the install so setup is one command
3. Draft the r/FuturesTrading and Show HN posts
4. Submit to awesome-selfhosted after one week of community feedback
