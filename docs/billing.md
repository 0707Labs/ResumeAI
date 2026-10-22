# Billing with Dodo Payments

How Resume Tailor takes payments: setting up products in the Dodo dashboard, the
webhook, going live, and what to do when a refund or dispute comes in.

Dodo Payments is our **merchant of record**. It sells to the customer, collects and
remits tax (GST, VAT, sales tax), and issues the receipt and invoice. We never issue
our own tax invoices, and no card data reaches our servers. Facts below come from
docs.dodopayments.com as read on 2026-10-21. Check anything marked *(verify)* in test
mode before relying on it.

Code map: catalog `backend/billing.toml`; provider `backend/app/billing/providers/dodo.py`;
webhook handling `backend/app/billing/events.py` and `webhooks.py`; ledger
`backend/app/billing/ledger.py`; admin metrics `backend/app/billing/admin.py`; CLI
`python -m app.billing.cli`; spending `backend/app/billing/analyses.py` and
`entitlements.py`. Local test-mode instructions are in the README
("Billing (Dodo Payments)").

---

## 1. How it fits together

1. `/pricing` → `POST /api/billing/checkout {product_key}`. The backend records a
   `payments` row, then creates a Dodo checkout session for the product id in
   `billing.toml`, with metadata `user_id` and `product_key`. The browser is sent to
   Dodo's hosted checkout.
2. Dodo returns the buyer to `/billing/success?payment=<our id>`. That page **only
   polls our backend**. The return URL's own `status` parameter is never trusted.
3. Dodo calls `POST /api/billing/webhooks/dodo`. After checking the signature, the
   backend matches the payment by checkout session id and grants credits or a pass
   **through the ledger, once**. This is the only place anything is granted.
4. Refunds, disputes and subscription changes arrive the same way and adjust the
   ledger exactly once, never below zero. Anything a person must look at becomes a
   review on `/admin/billing`.

---

## 2. Product setup in the Dodo dashboard

Do this in **Test mode** first. Products are separate per mode; when the test setup
works, use *Copy to live mode* on each product (details are kept) and put the live
ids in `billing.toml`.

Create these products. The names are what buyers see at checkout and on their
receipts.

| billing.toml key | Dodo product name | Type | Price | Notes |
|---|---|---|---|---|
| `credit_pack_5` | **Resume Tailor – 5 credits** | One-time | Base price in **USD** = `prices.USD`; add a localized price *By currency* for **INR** = `prices.INR` | One credit tailors one resume to one job |
| `job_hunt_pass` | **Resume Tailor – Job Hunt Pass (30 days)** | One-time | Same pattern: USD base, INR localized | 30 days, fair use 40 runs; the length lives in our code, not in Dodo |
| `pro_monthly` | **Resume Tailor Pro (monthly)** | Subscription | Same pattern; repeat payment every **1 month**; set the subscription period long (e.g. 10 years) so it doesn't end after one charge | Only while `products.pro_monthly.enabled` / `RT_BILLING_PRO_ENABLED` is on |

Settings for **every** product:

- **Tax-inclusive pricing: on.** `[display].prices_include_tax = true` makes the pricing
  page say "Prices include taxes"; that is only true if this is on. *(verify)* That
  tax-inclusive also applies to the localized INR price: buy in test mode with an
  Indian card and check the total equals the configured price.
- **Tax category:** `saas` (software as a service). `digital_products` also fits; pick
  one and keep it. Your CA should confirm.
- **Product metadata:** add `rt_product_key` = the billing.toml key (for example
  `credit_pack_5`), so exports and Dodo reports can be matched to our catalog. Our code
  doesn't read it.
- **Don't attach** Dodo credit entitlements, license keys, digital files or meters. Our
  own ledger is the source of truth. Dodo's credits lag about a minute and don't stop
  usage at zero.
- **Pay what you want, purchasing power parity, charm pricing:** off. The amount must
  match `billing.toml`.
- Prices are in minor units in both places (`49900` = ₹499.00, `600` = $6.00).

Checkout metadata keys we send on every session (don't rely on others):

| Key | Value | Used for |
|---|---|---|
| `user_id` | our user's UUID | Cross-check only. We map payments by checkout session id. |
| `product_key` | the billing.toml key | Cross-check only |

Business settings:

- **Discount codes:** we turn the code box off per checkout (`allow_discount_code: false`).
  Don't create codes unless the pricing page says so.
- **Adaptive Currency:** keep it **off**, or turn on **fees inclusive**. Otherwise buyers
  outside India and the US see a 2–4% conversion fee added at checkout, which the
  pricing page doesn't mention.
- **Branding** (Settings → Business → brand → Edit): name "Resume Tailor", logo (PNG,
  300×300). This is what appears on Dodo's invoices.
- **Customer emails:** leave the payment and refund receipts on. They are how buyers
  get invoices.
- **Visa RDR** is on by default (Visa disputes up to $100 are refunded automatically).
  Leave it on. It arrives as `dispute.lost` and our ledger handles it.

Then copy each product id (`pdt_...`) into `billing.toml` under
`dodo_product_id.test` / `.live`, and check:

```bash
cd backend && .venv/bin/python scripts/dodo_check_products.py
```

It exits 1 if a product is missing, has the wrong type, isn't tax-inclusive, or has a
price that differs from `billing.toml`. Run it after every price change and before
every deploy. **Changing a price:** change it in Dodo and in `billing.toml` together,
bump `version` in `billing.toml`, and run the check. Existing purchases keep what they
were promised; each payment stores a snapshot.

---

## 3. Webhook setup

In Developer → Webhooks, add an endpoint per mode:

- **URL:** `https://<public origin>/api/billing/webhooks/dodo`. The frontend's
  `/api/*` rewrite forwards it to FastAPI unchanged. If the backend has its own public
  host, point at that instead. Either way, use **Send example** to confirm the
  signature check passes. A 401 in Dodo's logs means the secret is wrong or the body
  was altered on the way.
- **Events:**
  - `payment.succeeded`, `payment.processing`, `payment.failed`, `payment.cancelled`
  - `refund.succeeded`, `refund.failed`
  - `dispute.opened`, `dispute.challenged`, `dispute.accepted`, `dispute.won`,
    `dispute.lost`, `dispute.cancelled`, `dispute.expired`
  - When Pro is enabled: all `subscription.*` events.

  Anything else is acknowledged and ignored.
- **Secret:** copy the endpoint's signing secret (`whsec_...`) into `DODO_WEBHOOK_SECRET`.
  Test and live endpoints have different secrets.

Env vars (`backend/.env`, never committed): `DODO_API_KEY`, `DODO_WEBHOOK_SECRET`,
`DODO_ENVIRONMENT=test|live`, optional `DODO_BUSINESS_ID` (for the customer-portal
login link), optional `RT_BILLING_PRO_ENABLED`. Without the key and secret, checkout
and the webhook answer 503. Nothing silently falls back to live mode.

How deliveries behave: Dodo signs with Standard Webhooks (`webhook-id`,
`webhook-timestamp`, `webhook-signature`; 5-minute tolerance). It retries non-2xx
responses 8 times over about a day, with a 30-second timeout, and doesn't guarantee
order. We dedupe on `webhook-id` (`processed_webhook_events`) and answer 5xx when
processing fails, so Dodo retries. A **Send example** event doesn't match any of our
checkouts, so it shows up as an "unknown payment" review. That's expected; mark it
resolved.

---

## 4. Go-live checklist

Account and compliance

- [ ] Dodo account verification passed; live payments and payouts enabled.
- [ ] **Written OK from compliance@dodopayments.com** for credit packs (their policy
      prohibits "stored value" and asks about credit packs as an edge case) and for a
      resume tool (listed as "needs extra review").
- [ ] Separate Dodo business (or brand) for 0707Labs, if it shouldn't share payouts
      with other MealOBox products.
- [ ] Your CA has confirmed the GST position for Dodo payouts (export of services / LUT)
      and the tax category.
- [ ] Terms, privacy and refund pages name Dodo Payments as merchant of record. They
      state our refund policy and that Dodo's refund and card-network dispute rules
      apply. The privacy notice names Dodo as a recipient of buyer data.

Products and config

- [ ] Real prices in `billing.toml` (the shipped ones are placeholders), `version` bumped.
- [ ] Products copied to live; live ids in `dodo_product_id.live`;
      `scripts/dodo_check_products.py` passes with `DODO_ENVIRONMENT=live`.
- [ ] Tax-inclusive verified with a test purchase in INR and in USD.
- [ ] `[fees.dodo]` matches Dodo's current pricing page. Then do one test purchase,
      compare `settlement_amount` with the Payouts → Balances entry, and set
      `settlement_is_net_of_fees` accordingly *(verify)*.
- [ ] `[llm_prices]` covers every model the app and its fallbacks can answer with
      (`/admin/billing` flags unpriced calls).
- [ ] Pro flag off unless Pro is ready.

Secrets and infrastructure

- [ ] Live `DODO_API_KEY` and live webhook endpoint with its own `DODO_WEBHOOK_SECRET`;
      `DODO_ENVIRONMENT=live` in production only.
- [ ] Migrations at head (`alembic upgrade head`).
- [ ] Cron runs `python -m app.billing.cli check-alerts` (exit 1 means alert) at least
      hourly and pages someone.
- [ ] Cron runs `python -m app.billing.cli purge-expired` daily (section 11); the Privacy
      Policy promises the `[retention]` periods.
- [ ] `NEXT_PUBLIC_SUPPORT_EMAIL` set, so the checkout-success page can link to support.
- [ ] At least one admin user: `UPDATE users SET role = 'admin' WHERE email = '...'`.

Final checks

- [ ] One small real purchase in live mode, then a full refund. The credits appear, then
      come back off, exactly once, and both show on `/admin/billing`.
- [ ] Every **test-mode subscription cancelled**. Test subscriptions keep renewing and
      sending webhooks until cancelled.

---

## 5. Refund runbook

**Who can refund:** Dodo processes refunds; we start them from the Dodo dashboard
(Transactions → payment → *Initiate refund*, full or partial). The app has no refund
button yet. `DodoProvider.refund()` exists for when one is added.

**Before you refund:**

1. Find the purchase on `/admin/billing` (buyer email, plan, Dodo payment id `pay_...`),
   and the buyer's credit history (`credit_transactions` for their user id).
2. Check Dodo's limits:
   - The payment must have succeeded and be **at most 30 days old**. Dodo's standard
     customer-request window is 7 days.
   - Our Dodo **balance must cover the refund**, or Dodo denies it.
   - Only one refund per payment can be pending or in review at a time.
   - Dodo keeps the original fee and charges $1 per refund.
3. Decide full or partial. Our policy: a pack whose credits are all unused, or a pass
   with no runs, can be refunded in full. Otherwise refund the unused share or decline,
   per the published refund policy.

**What happens automatically after `refund.succeeded`:**

- **Full refund of a pack:** the pack's credits are taken back, once. If some were
  already spent, only what's left is taken. The balance never goes negative, and a
  **"Refund after credits were spent"** review records the shortfall.
- **Partial refund of a pack:** credits are taken back in proportion to the amount,
  rounded down. If the refund's currency differs from the payment's, nothing is changed
  and a **"Partial refund to check"** review is raised.
- **Pass:** a full refund revokes the pass. A partial refund raises a review and leaves
  the pass as it is.
- The payment shows as Refunded or Partly refunded. Redeliveries of the same refund
  (even under a new delivery id) change nothing.

**Reviews after a refund:**

- *Refund after credits were spent:* usually accept the loss. If the buyer should lose
  the credits they still had from a later purchase, take them back by hand (below) and
  say why.
- *Partial refund to check:* work out the credits to take back and adjust by hand.
- Then **Mark resolved** on `/admin/billing`.

**Adjusting credits by hand** (always with a note; `--key` makes a retry safe):

```bash
cd backend && .venv/bin/python -m app.billing.cli adjust-credits <user_id> -2 \
  --note "partial refund rfd_123 on pay_456" --key "rfd_123"
```

Positive numbers add credits. It refuses to go below zero.

`refund.failed` changes nothing on our side. Fix the cause in Dodo (often the balance)
and refund again.

---

## 6. Dispute runbook

A dispute (chargeback) is the card network reversing a payment. Dodo debits the
disputed amount **and a $30 fee** (not returned even if we win) as soon as it opens.

1. **`dispute.opened`:** the payment shows as *Under dispute* and a **"Dispute opened"**
   review appears. Credits are left alone while it's open.
2. **Respond in Dodo within 10 days** (the dashboard shows a countdown):
   - **Accept** if the buyer has a point. Accepting refunds them, and our ledger reverses
     the purchase on `dispute.accepted` / `dispute.lost`.
   - **Counter** with evidence: the account email and sign-in history, purchase time,
     the receipt Dodo sent, the credit history showing what was used (from
     `credit_transactions`), and the terms they accepted at sign-up (`consent_records`).
3. **`dispute.lost`** (including Visa RDR auto-refunds up to $100, marked
   `is_resolved_by_rdr`): the pack's remaining credits are taken back, or the pass is
   revoked, exactly once, never below zero. Spent credits raise a **"Refund after
   credits were spent"** review. If refund events for the same payment came earlier,
   nothing is taken twice.
4. **`dispute.won` / `cancelled` / `expired`:** the payment goes back to *Paid*; nothing
   else changes.
5. Mark the review resolved. Repeated disputes from one account are a reason to suspend
   it (`users.status = 'suspended'`).

Ethoca alerts (opt-in, Mastercard) refund automatically and arrive as normal refund
events.

---

## 7. When a webhook didn't arrive or keeps failing

- Symptoms: the buyer paid but `/billing/success` timed out. Or a **"webhook event(s)
  failed"** alert, or entries under *Webhooks not yet processed* on `/admin/billing`.
- Look at the failure count and error class there, and at the endpoint's **Logs** in
  Dodo.
- Fix the cause (database down, bad deploy, wrong secret), then redeliver from Dodo:
  open the message in **Logs → Replay**, or **More actions → Recover failed messages**
  for a batch. Dodo also retries on its own for about a day.
- **Don't grant purchases by hand** for a payment whose webhook is pending: the replay
  will grant it, and a manual grant on top would give it twice. Only use
  `adjust-credits` for a payment Dodo confirms paid but whose webhook can't be
  delivered, and put the Dodo payment id in the note.

---

## 8. Money in the admin view

`/admin/billing` shows revenue from Dodo's **settlement** amounts (USD for INR and most
other currencies), minus the tax Dodo collected, minus refunds, minus **estimated** Dodo
fees from `[fees.dodo]`:

- India: 4% + 15¢
- Elsewhere: 4% + 40¢, plus 1.5% for international cards
- Subscriptions: +0.5%
- $1 per refund, $30 per dispute

Dodo reports no fee per payment, so check the estimates against payout reports.
"Margin if fully used" assumes every credit or pass run is used, at the average LLM
cost per analysis from `llm_usage` (priced from `[llm_prices]`).


---

## 9. Spending: tailoring is free to try, the download pays

Tailoring and reviewing cost nothing, so people see the value first. The clean DOCX/PDF
download is what spends a credit. Code: `app/billing/entitlements.py` (decisions),
`app/billing/analyses.py` (starts and downloads), `/api/analyses` and `/api/downloads`.

- **Analyze** (signed in) calls `POST /api/analyses`. It pins the parsed resume and job
  description on the server (`analyses.resume`, `.jd`, `.inputs_sha256`) and spends
  nothing. Holding the user's row lock, `can_start_tailoring` allows it with a **free
  tailoring** (`[free].analyses_per_month`, calendar month in UTC; runs that ended
  rules-only don't count), or past those with whatever a download would need (below).
  Nothing left: **402 `no_credits`** and the pricing dialog ("free tailorings used").
  `GET /api/analyses/allowance` tells the workspace what's left and when it resets.
- **Claude is used only for the caller's own analysis and its pinned inputs.** Signed
  out, or with an unknown, someone else's or expired (`[analyses].usable_hours`)
  analysis, or with a resume or job description other than the pinned ones, every stage
  runs rules-only. Claude tailors once per analysis; the first result is stored on it
  (`tailored`, `llm_tailored`). `llm_usage.analysis_id` is the checked server-side id.
- **Claude has a daily cap per user.** At most `[analyses].claude_analyses_per_day`
  (10) analyses a day may use Claude, or `paid_claude_analyses_per_day` (30) with an
  active pass or Pro. The count is the user's analyses started since 00:00 UTC that may
  use Claude, taken in `start_analysis` under the user's row lock, so concurrent starts
  can't go past it. Past the cap the analysis **still starts** (after the same
  free-tailoring gate) and downloads and pays like any other, but is rules-only: its
  `usable_until` is its `created_at`, it doesn't use up a free tailoring, the response
  has `claude: false` with the cap in `claude_per_day`, and the pipeline's note and the
  app say today's Claude analyses are used up until 00:00 UTC. Idempotent replays don't
  count again. A `0` turns Claude off.
- **Downloading** is two requests. `POST /api/downloads/{docx,pdf}` needs sign-in, CSRF
  and the analysis (`X-Analysis-Id`). Holding the user's row lock it decides what pays
  (`can_user_run`): a paid download of the **same analysis** less than
  `[downloads].redownload_free_days` ago (default 7) covers it (`paid_with = 'window'`);
  otherwise an **active pass** under its fair-use cap, then **Pro** under its per-period
  cap, then **credits** (`[downloads].credits_per_download`, ledger key
  `download:{download_id}`, reason `analysis_charge`). Fair-use caps count paid
  downloads. Nothing left: **402 `no_credits`**, no row, no file. Then it renders the
  file once inside the same transaction (a failed render charges nothing) and returns a
  **signed link** (`/api/downloads/file/{token}`, HMAC with `RT_AUTH_SECRET`, valid
  `[downloads].url_ttl_seconds`, default 120). `GET` on the link serves the file only to
  the user who paid, only until it expires (410 after), with `Cache-Control: no-store`.
- The file is built from the pinned resume and job description; the browser's approved
  and edited bullets are re-verified against that resume. Nothing is rendered before the
  entitlement check passes.
- Every download is a `downloads` row (format, what paid, credits, served_at) and one
  `app.billing` log line with ids only; no resume text is logged.
- After the retention purge (section 11) a re-download of that analysis gets **410
  `analysis_expired`** and nothing is charged; the workspace says the re-download period
  has passed, forgets the analysis id and asks to tailor again. A signed link whose
  download was purged gets 410 `link_expired`.
- **Pricing dialog for a download:** buying from it remembers the format in the tab
  (sessionStorage). `/billing/success` waits for the webhook as before, then sends the
  buyer to `/app/export?resume=download`, which starts the download once.
- Concurrent clicks are safe: the row lock serializes them, so one pays and the rest
  fall in the window; credits never go below zero.
- Credit-backed tailorings have no monthly cap of their own: a user with one credit can
  keep tailoring. The daily Claude cap above bounds what that costs (about the cap times
  one analysis's Claude cost per user per day); the daily LLM spend alert (`[alerts]`)
  still watches the total.

---

## 10. Referrals

Code: `app/billing/referrals.py`, `/api/referrals`, `/api/admin/referrals`; config
`[referrals]` in `billing.toml`.

- Every user has a code (made on first visit to `/account/referrals`); the link is
  `{RT_PUBLIC_URL}/?ref=CODE`. Any page keeps a valid `?ref` in the first-party `rt_ref`
  cookie for 30 days. The first friend's link wins.
- **Attribution** happens in the account-creating transaction (`complete_signup`): one
  `referrals` row per new account (a referee is attributed once). Rejected up front:
  the same person (same address after removing `+tags`, and Gmail dots), and disposable
  email domains (built-in list plus `extra_disposable_domains`). From the
  `same_ip_review_threshold`-th referred sign-up on one network within
  `review_window_hours`, each new one waits for review (`needs_review`). Networks are
  compared by a keyed hash, never stored as addresses. We don't fingerprint devices.
- **Reward** on the configured `trigger`: `on_verified_signup` (when the account is
  created; every sign-up has a verified email by then) or `on_first_tailoring` (default:
  when the friend's first tailoring finishes). It goes through the ledger: reason
  `referral`, `reference_id` = referral id, key `referral:{id}`, so it is paid once.
  `reward_credits` (1) to the referrer, plus optional `invitee_reward_credits`. At most
  `monthly_cap` (10) rewards per referrer per calendar month; over it, the referral is
  rejected (`over_monthly_cap`). Rewards lock the referrer's row, so concurrent triggers
  can't exceed the cap.
- **Invites quota:** each user has `invites_per_user` (10) invite slots, shared by
  email invites (`/app/invites`, bound to the friend's address, 30 days, no code to type)
  and, in invite-only mode, sign-ups that use their referral link as the invite. The
  counter (`users.invites_created`) is changed only by the `create_user_invite`,
  `revoke_user_invite` and `take_invite_slot` Postgres functions (migration 0013), which
  lock the user's row, so concurrent requests can't pass the limit. Revoking an unused
  invite returns its slot. A friend who joins through an email invite is attributed to
  the sender, so the referral reward follows.
- **Live feedback:** the workspace header polls `/api/referrals/updates` every 30 s and
  on focus. It shows the balance and, once per reward, "Your friend joined. +1 credit".
- **Admin queue** (`/admin/referrals`): approve a flagged one (it pays if its trigger
  already fired), reject it with a reason, or reverse a paid one. A reversal takes the
  credits back (key `referral-reversal:{id}`), never below zero.

---

## 11. Data retention

Resume text is kept only as long as the product needs it. Periods are `[retention]` in
`billing.toml`, and the Privacy Policy (`frontend/app/legal/privacy/page.tsx`) quotes
them, so change both together. Code: `app/billing/retention.py`; migration
`0009_retention`.

| What | Cleared | Default |
|---|---|---|
| `analyses.resume`, `.jd`, `.tailored` | `analysis_days` after the analysis's last download, or after it started if never downloaded; never while `usable_until` is ahead | 30 days |
| `downloads.final_resume` (what the signed link renders) | `download_days` after the download; unset means `[downloads].redownload_free_days` | 7 days |

- **What stays:** ids, owner, timestamps, `inputs_sha256`, `llm_tailored` and
  `tailored_at`, `paid_with`, the pass or subscription, and `credits`. Billing, fair-use
  caps, the monthly free tailorings and referral triggers read these, so they count the
  same before and after a purge. A purged row has `purged_at` set; check constraints keep
  rows either whole or fully purged.
- **Config checks:** `analysis_days` must be at least `redownload_free_days` (a free
  re-download always finds its analysis) and longer than `[analyses].usable_hours`.
  Startup fails otherwise.
- **Running it:** `cd backend && .venv/bin/python -m app.billing.cli purge-expired`.
  It prints how many analyses and downloads it cleared and logs one `app.billing` line
  with counts only. It is idempotent (only rows with `purged_at IS NULL` are touched)
  and batched: each `batch_size` rows (500) commit on their own, and rows a download is
  holding right now are skipped until the next run. Run it daily from cron:

  ```
  15 3 * * * cd /srv/resume-tailor/backend && .venv/bin/python -m app.billing.cli purge-expired >> /var/log/resume-tailor/purge.log 2>&1
  ```

  It needs the same `RT_DATABASE_URL` as the app. Missing a day only delays deletion;
  the next run catches up.
- **In the app:** a purged analysis can't be used for Claude or downloaded: `POST
  /api/downloads/{fmt}` answers 410 `analysis_expired` (nothing charged), the workspace
  asks to tailor again. The download takes a row lock on the analysis, so a purge never
  clears one mid-download.
- **Deleted accounts:** analyses and downloads keep `user_id = NULL`; the purge clears
  their text on the same schedule.
- **Not covered:** Postgres keeps old row versions until (auto)vacuum reclaims them, and
  database backups keep text for as long as backups are retained. Keep backup retention
  in line with the Privacy Policy.

---

## 12. Claude costs, budgets and the dashboard rollups

Code: `app/billing/costs.py` (recording), `app/billing/budget.py` (budgets, kill switch,
alerts), `app/billing/aggregates.py` (rollups), `/api/admin/costs`, `/api/admin/revenue`;
migration `0015_costs_revenue`.

- **Every call is recorded**, answered or not: one `llm_usage` row with the model that
  answered, tokens, cost (from `[llm_prices.*]`), the user (from the analysis), latency,
  and a status: `ok`, `refused`, `truncated`, `invalid` (didn't match the schema),
  `error` or `rate_limited` (with a short `error_code` like `api_429`). Calls that got an
  answer we couldn't use count as *wasted* spend. Schema names map to pipeline steps in
  `costs.PIPELINE_STEPS` (gap analysis, tailor, tailor repair, ATS semantic, mentor).
- **What allowed each analysis** (`analyses.entitlement`: free, pass, pro, credit) is
  kept, so costs split by plan and the free tier's burn shows.
- **Budgets** are runtime settings (superadmin, `/admin/costs`): `daily_budget_usd`
  (default `[alerts].daily_llm_spend_usd`), `monthly_budget_usd` (default 30x daily) and
  `budget_kill_switch` (default on). Spend is counted from 00:00 UTC and the 1st of the
  month, UTC.
- **Kill switch:** when a budget is used up and the switch is on, `POST /api/analyses`
  answers **503 `analyses_paused`** and the workspace says tailoring is paused. Analyses
  already running finish. It lifts by itself when the day or month turns, or when staff
  raise the budget. `analyses_paused` (a manual switch) pauses the same way. Signed-out,
  rules-only use never touches Claude, so it isn't affected.
- **Alerts** at 50%, 80% and 100% of each budget, once per period
  (`budget_alerts`): email to active admins and superadmins, and a Slack message when
  `RT_SLACK_WEBHOOK_URL` is set (only `https://hooks.slack.com/` URLs are used).
- **Per-user caps** stay as in section 9 (`claude_analyses_per_day` /
  `paid_claude_analyses_per_day`); the costs page shows them.
- **Rollups** (`daily_llm_costs`, `daily_revenue`) feed the dashboard. Each run
  recomputes the last N days and replaces them, so late webhooks and refunds land on the
  next run. Revenue uses the same per-payment arithmetic as `/admin/billing`.
- **Refunds from the admin** (`POST /api/admin/revenue/payments/{id}/refund`,
  billing.write) call Dodo through the provider interface and are audited; Dodo's
  webhook then updates the payment and takes back credits as in section 6. A partial
  refund needs the product's Dodo id in `billing.toml`. Disputes have no API: answer
  them in Dodo's dashboard.

Cron (same environment as the app):

```
*/15 * * * * cd /srv/resume-tailor/backend && .venv/bin/python -m app.billing.cli refresh-aggregates
*/5 * * * *  cd /srv/resume-tailor/backend && .venv/bin/python -m app.billing.cli budget-check
```

Run `refresh-aggregates --days 400` once after deploying to fill history.
