# Tests for the landing → sign-in → tailor → paywall → referral journey

Where each requirement from the spec's Step 7 is tested. Backend tests run against real
Postgres (pytest creates and drops a throwaway database). E2E runs Chromium against the
real backend in rules-only mode.

| Requirement | Backend (pytest) | Frontend unit (Vitest) | E2E (Playwright) |
|---|---|---|---|
| Signed-out user can't reach /app | — | `protection.test.tsx` (proxy redirects) | `protection.spec.ts`: /app and /app/* go to /signin?next=…; a stale cookie is caught by the server-side check |
| Signed-out user can't reach the download endpoint | `test_analyses.py::test_download_needs_sign_in_and_an_analysis`, `::test_a_signed_link_is_for_its_owner_only_and_expires` | — | — |
| Download without entitlement: 402 and no file | `test_analyses.py::test_without_entitlement_402_and_no_file_is_generated` | `api.test.ts` (402 opens the dialog) | `happy-path.spec.ts`: the pricing dialog, no download event |
| A download spends exactly one credit; re-download in the window spends none | `test_analyses.py::test_a_download_charges_one_credit_and_re_downloads_in_the_window_are_free`, `::test_the_redownload_window_is_configurable`, `::test_a_paid_download_gives_a_signed_link_and_re_downloads_are_free` | `Export.test.tsx` | `happy-path.spec.ts`: "1 credit used; 4 left", then the PDF is free |
| Concurrent clicks never double-charge or go negative | `test_analyses.py::test_concurrent_clicks_on_one_download_charge_once`, `::test_concurrent_downloads_never_overspend_or_go_negative`, `::test_concurrent_downloads_never_exceed_a_pass_cap` | — | — |
| Purchase → webhook → credits → download (test mode) | `test_purchase_to_download.py` (checkout through the Dodo provider with a mocked API, signed webhook, replay, download) | `billing.test.tsx` (dialog remembers the download; success page returns to it), `Export.test.tsx` (download finishes after return) | `happy-path.spec.ts`: Buy → /billing/success → signed `payment.succeeded` → back to export → the DOCX downloads by itself |
| Referral rewarded once on the configured trigger | `test_referrals.py::test_reward_on_first_tailoring_once`, `::test_reward_on_verified_signup_with_an_invitee_reward` | — | `referral.spec.ts`: link → friend joins → first tailoring → referrer credited |
| Self-referral and same-email aliases blocked | `test_referrals.py::test_same_person_and_disposable_email_are_rejected`, `::test_aliases_of_one_address_are_one_person` | — | — |
| Duplicate referee blocked | `test_referrals.py::test_a_referee_is_attributed_once` | — | — |
| Over-cap blocked | `test_referrals.py::test_rewards_stop_at_the_monthly_cap` | — | — |
| Disposable email blocked | `test_referrals.py::test_same_person_and_disposable_email_are_rejected`, `::test_disposable_domains_and_codes` | — | — |
| Referrer's balance updates | `test_referrals.py::test_live_updates_show_a_new_reward_once` | `referrals.test.tsx` (header balance, polling, one-time notice) | `referral.spec.ts`: header shows "1 credit" and "Your friend joined. +1 credit" once |
| Same-network review, admin approve, reject and reverse | `test_referrals.py::test_many_signups_from_one_network_wait_for_review`, `::test_admin_queue_approves_rejects_and_reverses` | `referrals.test.tsx` (admin queue) | — |
| Invite-only: a referral link is the invite, within the limit | `test_referrals.py::test_invite_only_a_referral_link_works_as_an_invite_up_to_the_limit` | `referrals.test.tsx` (invite page) | `referral.spec.ts` |
| One invite quota (10) for email invites and link sign-ups; the 11th is refused, also with 25 concurrent requests | `test_invites_support.py::test_the_eleventh_invite_is_refused_under_concurrency`, `::test_link_sign_ups_and_email_invites_share_the_quota_under_concurrency`, `::test_link_sign_ups_use_the_same_quota` | `invitesSupport.test.tsx` (quota, send, revoke) | `referral.spec.ts` (a link sign-up uses a slot) |
| Users never see each other's downloads, invites, tickets, resumes or tailorings | `test_invites_support.py::test_users_never_see_each_others_*`, `test_profile.py::test_user_a_cannot_touch_user_bs_resumes_or_tailorings`, `test_admin_security.py::test_rt_app_sees_only_its_own_rows` | — | — |
| Free tailorings, then the pricing dialog | `test_analyses.py::test_past_the_free_tailorings_starting_needs_a_pass_pro_or_credits` | `protection.test.tsx` (allowance note) | `limits.spec.ts`, `happy-path.spec.ts` step 7 |
| Preview protection | `test_export.py::test_preview_is_images_only_never_the_text`, `::test_preview_is_watermarked_and_masked`, `::test_downloads_carry_a_quiet_reference_to_the_download` | `Export.test.tsx` | `happy-path.spec.ts` (no resume text on the page) |

## Where Playwright's browser lives

On this Mac something clears `~/Library/Caches`, which is where Playwright keeps its
browsers by default, so e2e failed with `Executable doesn't exist ... chrome-headless-shell`
twice. Keep the browser outside that folder by setting `PLAYWRIGHT_BROWSERS_PATH`, for
both the install and every run (all worktrees can share one copy):

```bash
export PLAYWRIGHT_BROWSERS_PATH="$HOME/0707Labs/.playwright-browsers"
npx playwright install chromium   # once, or after a Playwright upgrade (~95 MB)
npm run test:e2e
```

Put the `export` in your shell profile to make it stick. Without it Playwright falls
back to `~/Library/Caches/ms-playwright`, which works until the cache is cleared.

## E2E and the magic-link rate limit

Every e2e account signs up by magic link, and the backend allows 5 magic links per 15
minutes per IP. The suite needs about 9 per run.

**What we do:** `RT_DEV_RATE_LIMIT_SCALE` multiplies every rate limit, at most ×100, but
only when `RT_PUBLIC_URL` is a localhost origin. `playwright.config.ts` sets it to 10
for the backend it starts. A deployed instance (non-localhost public URL) ignores it, so
production keeps its limits even if the variable leaks into its environment.
`test_auth_session.py::test_dev_rate_limit_scale_only_applies_on_localhost` checks this.

Options we didn't take:
- A test-only sign-in route in e2e: faster, but more test-only code paths in the app that
  must never be switched on in production.
- Spreading runs over time, or reusing accounts across specs: slow, and specs would
  depend on each other's order.
- Faking client IPs with `X-Forwarded-For`: uvicorn trusts it only from 127.0.0.1 (the
  Next.js proxy), and leaning on that would weaken a real protection.

A backend you started yourself (reused by Playwright) doesn't get the variable. Set it
there too, or restart between runs.

## Payments in e2e

Dodo's hosted checkout can't run in CI. `e2e/helpers.ts` answers `POST /api/billing/checkout`
in the browser, recording the payment row the way the endpoint does, and sends the buyer
to our `/billing/success`. Everything after that is real: `scripts/dodo_send_webhook.py`
sends a Standard-Webhooks-signed `payment.succeeded` with the e2e secret, which goes
through signature checks, idempotency and the ledger. Checkout against Dodo's real test
mode is covered by the manual steps in the README ("Billing (Dodo Payments)").
