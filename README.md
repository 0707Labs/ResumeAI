# Resume Tailor

Tailor a resume to a job description **without fabricating experience**, score it
for ATS fit, and get mentor-style advice on whether to apply and what to learn.

Every rewritten bullet cites the original bullet(s) it came from, and a
deterministic verifier blocks anything new: tools, numbers, titles, employers, or
stronger verbs. Missing requirements become questions to you; only your own
answers can add a fact.

## Quick start

Backend (Python 3.11):

```bash
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload
```

Frontend (Node 20.9+):

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3000 and click **Use the sample resume and JD** to try it.

### Claude (optional)

Everything works rules-only. To let Claude review unclear gaps, rewrite bullets,
judge semantic relevance, and polish mentor wording, set `ANTHROPIC_API_KEY` in the
backend's environment (see `backend/.env.example`). Claude output always goes back
through the same verifier, and blocked rewrites fall back to your original wording.
Calls use `claude-opus-5-5` with server-side refusal fallbacks enabled.

## How it works

1. **Parse** the resume (PDF/DOCX/TXT) into sections, entries, and bullets with
   stable IDs (`exp1.b2`), plus format warnings. Parse the JD into required and
   preferred requirements with normalized keywords.
2. **Gap analysis** marks each requirement Evidenced, Implied, or Missing, and asks
   neutral questions for anything not evidenced.
3. **Tailor**: reorder by relevance, mirror JD spellings, and (with Claude) reword.
   The **verifier** checks each bullet against only its cited sources.
4. **Review**: approve, reject, or edit each bullet in a word diff. Edits are
   re-verified, and you can cite your confirmed answers.
5. **ATS score**: required keywords 40%, preferred 10%, semantic relevance 20%,
   title/seniority 10%, format 10%, quantified impact 10%, before vs after.
   Real ATS systems differ; treat it as an estimate.
6. **Mentor**: strengths, ranked gaps, actions, a should-you-apply verdict, and a
   two-week upskilling plan.
7. **Export** DOCX or PDF. Only approved bullets that re-verify on the server use
   tailored wording.

## Sign-in email

Magic links go to `backend/.dev-outbox/` by default (`RT_MAILER=outbox`), for dev and
the e2e tests. Production sends them through Amazon SES (`RT_MAILER=ses`), and the server
refuses to start without a sender and keys. SES setup, the send-only IAM policy,
SPF/DKIM/DMARC records and the go-live checklist are in [docs/email.md](docs/email.md).

## Admin access

Staff roles are `support`, `admin` and `superadmin`. To make the first superadmin, sign up
normally, then run:

```bash
cd backend && ADMIN_BOOTSTRAP_EMAIL=you@example.com .venv/bin/python -m app.auth.cli bootstrap-admin
```

Roles, the audit log, step-up re-authentication and the database's row-level security
(including the one-time `rt_app` role setup) are in [docs/admin.md](docs/admin.md).

## Billing (Dodo Payments)

Payments go through Dodo Payments, the merchant of record (it handles tax and issues
receipts). Credits and passes are granted **only** from verified webhooks, never from the
checkout redirect. Product ids, prices, credits, pass length, caps, fee estimates and LLM
prices live in `backend/billing.toml`. Dashboard setup, the webhook, the go-live
checklist and the refund/dispute runbook are in [docs/billing.md](docs/billing.md).

### Run it locally in test mode

1. In the Dodo dashboard, switch to **Test mode** and create the products from
   `billing.toml` (a one-time credit pack and a one-time pass; Pro is a subscription and
   stays hidden while its flag is off). Copy each `pdt_...` id into its
   `dodo_product_id.test` in `billing.toml`.
2. Install the Dodo CLI (`npm install -g dodopayments-cli`) and log in with your
   **test** key: `dodo login "<test API key>" test`.
3. Start the webhook relay. It creates a test webhook endpoint in the dashboard and
   forwards real test events, signatures intact, to your machine:

   ```bash
   dodo wh listen http://localhost:8000/api/billing/webhooks/dodo
   ```

   Then copy that endpoint's signing secret (Developer → Webhooks → the CLI's endpoint,
   `whsec_...`). A tunnel such as `cloudflared tunnel --url http://localhost:8000` also
   works: point a test endpoint at `<tunnel>/api/billing/webhooks/dodo`.
4. Fill in `backend/.env` (see `.env.example`): `DODO_API_KEY` (test key),
   `DODO_WEBHOOK_SECRET` (step 3), `DODO_ENVIRONMENT=test`, and optionally
   `DODO_BUSINESS_ID`. Check the dashboard matches the catalog:

   ```bash
   cd backend && .venv/bin/python scripts/dodo_check_products.py
   ```

5. Start the backend with that env and the frontend, sign in, open `/pricing` and buy.
   Pay with a test card (`4242 4242 4242 4242`, any future expiry, CVC `123`; India:
   `4576 2389 1277 1450`; UPI `success@upi`). The success page waits for the webhook
   and then shows your credits:

   ```bash
   cd backend && .venv/bin/uvicorn app.main:app --reload --env-file .env
   ```

6. Refunds and disputes: refund the payment in the dashboard (Transactions → Initiate
   refund) and watch the balance drop on `/account/billing`; anything needing a human
   shows on `/admin/billing` (admins only).

`dodo wh trigger` sends **unsigned** mock events, which our endpoint rejects with 401 by
design (we never skip verification). To exercise the whole path without a real checkout,
sign events locally with your secret instead:

```bash
cd backend && .venv/bin/python scripts/dodo_send_webhook.py payment.succeeded --payment-row <payments.id>
```

It also sends `refund.succeeded` (`--partial N`) and `dispute.opened|lost|won`, and
`--msg-id` replays the same delivery. It refuses to run unless `DODO_ENVIRONMENT=test`.

Alerts (failing webhooks, daily LLM spend over `[alerts]` in `billing.toml`) print from
`python -m app.billing.cli check-alerts`, which exits 1 when there are any; run it from cron.

### What the billing tests cover

| Requirement | Tests |
|---|---|
| Invalid signature rejected (bad, wrong secret, missing headers, stale, re-serialized body) | `test_dodo_provider.py::test_bad_webhooks_are_rejected`, `test_billing_webhooks.py::test_bad_signatures_are_rejected_with_401_and_change_nothing` |
| Replayed event ignored; concurrent first deliveries grant once | `test_billing_webhooks.py::test_replayed_event_is_ignored`, `::test_concurrent_deliveries_grant_once`, `::test_same_payment_under_a_new_delivery_id_grants_once` |
| Valid event grants credits once | `test_billing_webhooks.py::test_valid_payment_grants_credits_once` |
| Unknown event type safely ignored | `test_billing_webhooks.py::test_unknown_event_type_is_acknowledged_and_ignored`, `test_dodo_provider.py::test_unknown_event_type_still_verifies_and_parses` |
| Concurrent grants and charges never go negative | `test_ledger.py::test_concurrent_charges_never_overspend`, `::test_concurrent_grants_and_charges_stay_consistent`, `test_billing_webhooks.py::test_grants_racing_charges_never_go_negative` |
| Refund adjusts the ledger once (incl. redelivery, concurrency, spent credits) | `test_billing_webhooks.py::test_full_refund_takes_back_credits_exactly_once`, `::test_partial_refund_redelivered_under_a_new_id_applies_once`, `::test_concurrent_refund_deliveries_take_credits_back_once`, `::test_refund_after_credits_were_spent_never_goes_negative_and_flags` |
| Tampered price or user id in checkout ignored | `test_billing_checkout.py::test_tampered_price_and_user_id_are_ignored`, `test_dodo_provider.py::test_checkout_sends_config_product_and_our_metadata` |

## Tests

```bash
cd backend && .venv/bin/pytest
```

```bash
cd frontend && npm test && npm run typecheck && npm run build
```
