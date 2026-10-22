# Email: magic links through Amazon SES

Resume Tailor sends one kind of email: the magic sign-in link. `RT_MAILER` picks how
it is sent:

| `RT_MAILER` | Where it goes | Use |
|---|---|---|
| `outbox` (default) | a file in `backend/.dev-outbox/` | local dev, pytest, Playwright e2e |
| `ses` | Amazon SES v2 API in `RT_SES_REGION` (default `ap-south-1`, Mumbai) | staging and production |

The SES mailer (`backend/app/auth/mailer.py`) signs requests itself with SigV4. It needs
no AWS SDK, so credentials come only from the environment (see "Credentials" below).
Every email has a plain-text part and a simple HTML part with the same link.

The app **refuses to start** when `RT_MAILER=ses` is missing `RT_MAIL_FROM`,
`AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY`. It also refuses to start for an unknown
`RT_MAILER`. If SES rejects a send or can't be reached, the sign-in request gets
`503 email_unavailable` (the page suggests Google or GitHub), and an auth event
`magic_link_failed` is logged with only the status (`ses_400`, `network`, ...). The address,
token and link are never logged. SES error bodies can name the recipient, so they are
dropped.

Below, `example.com` stands for the product's domain and `mail.example.com` for the sending
subdomain. Use the real names.

## 1. SES setup (AWS console, region ap-south-1)

1. **Create the identity.** SES → Configuration → Identities → Create identity → Domain
   → `mail.example.com`. Under *Advanced DKIM settings*, pick **Easy DKIM**, RSA 2048-bit.
2. **Custom MAIL FROM domain.** On the identity, set the MAIL FROM domain to
   `bounce.mail.example.com`. Set *Behavior on MX failure* to "Use default MAIL FROM
   domain". Without this, SPF only covers `amazonses.com` and doesn't align with your domain.
3. **Publish the DNS records** in section 2 below. Wait until the identity shows
   *DKIM: Successful* and *MAIL FROM: Successful*. This usually takes minutes, up to 72 hours.
4. **Leave the sandbox.** Account dashboard → *Request production access*. Use case:
   transactional sign-in links only, sent on request, about N per day, no marketing. Bounces
   and complaints go to the account suppression list. In the sandbox, SES delivers only to
   verified addresses, 200 per day.
5. **Suppression list.** Account dashboard → Suppression list: make sure **Bounces and
   complaints** are both on. Then SES stops sending to addresses that hard-bounced or
   complained.
6. **Optional: configuration set** `magic-links` with event publishing (bounce,
   complaint, delivery delay) to SNS or EventBridge, plus a CloudWatch alarm. Keep bounces
   under 5% and complaints under 0.1%, or AWS reviews the account. Set
   `RT_SES_CONFIGURATION_SET=magic-links` to use it.

### Credentials

Create an IAM user (or role) that can do nothing but send from this identity:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "ses:SendEmail",
    "Resource": [
      "arn:aws:ses:ap-south-1:<ACCOUNT_ID>:identity/mail.example.com",
      "arn:aws:ses:ap-south-1:<ACCOUNT_ID>:configuration-set/magic-links"
    ],
    "Condition": {"StringEquals": {"ses:FromAddress": "no-reply@mail.example.com"}}
  }]
}
```

(Drop the configuration-set ARN if you don't use one.) Put its access key in
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. Temporary credentials also need
`AWS_SESSION_TOKEN`. The mailer reads only these environment variables. It does not
fetch instance-profile or ECS task-role credentials, so on EC2 or ECS inject keys from
your secret store, or set all three variables from the role yourself. Rotate the key like
any other secret.

## 2. DNS: SPF, DKIM, DMARC

Add these at your DNS host. SES shows the exact DKIM tokens on the identity page.

| Purpose | Type | Name | Value |
|---|---|---|---|
| DKIM (×3) | CNAME | `<token1>._domainkey.mail.example.com` | `<token1>.dkim.amazonses.com` |
| | CNAME | `<token2>._domainkey.mail.example.com` | `<token2>.dkim.amazonses.com` |
| | CNAME | `<token3>._domainkey.mail.example.com` | `<token3>.dkim.amazonses.com` |
| MAIL FROM (bounces) | MX | `bounce.mail.example.com` | `10 feedback-smtp.ap-south-1.amazonses.com` |
| SPF | TXT | `bounce.mail.example.com` | `v=spf1 include:amazonses.com ~all` |
| DMARC | TXT | `_dmarc.mail.example.com` | `v=DMARC1; p=none; rua=mailto:dmarc-reports@example.com; adkim=r; aspf=r` |

Notes:

- **SPF** goes on the MAIL FROM domain (`bounce.mail.example.com`), because receivers check
  SPF against the envelope sender, not the `From:` header. Don't add `amazonses.com` to the
  root domain's SPF unless something else sends from the root through SES.
- **DKIM** signs as `mail.example.com`, so DKIM and DMARC align with
  `From: no-reply@mail.example.com`. DMARC passes on DKIM alone. The aligned SPF is a
  second path.
- **DMARC**: start at `p=none` and read the aggregate reports (`rua`) for 2–4 weeks.
  Once only SES (and any other senders you expect) pass, move to `p=quarantine`, then
  `p=reject`. If `example.com` already has a DMARC record, the subdomain record above
  overrides it for `mail.`. Without one, the root's `sp=` policy applies. A DMARC record
  on the root (`_dmarc.example.com`) is good practice anyway, even if the root sends no mail.
- Gmail and Yahoo require SPF or DKIM and a DMARC record from bulk senders. We're far below
  their bulk threshold, but meeting the rules anyway keeps links out of spam.
- Check after DNS propagates: send a link to a Gmail address and open *Show original*.
  It should show `SPF: PASS`, `DKIM: PASS` and `DMARC: PASS`, all with `mail.example.com`
  or `bounce.mail.example.com`.

## 3. App configuration

In the backend's production environment (never in a committed file):

```bash
RT_MAILER=ses
RT_MAIL_FROM="Resume Tailor <no-reply@mail.example.com>"
RT_SES_REGION=ap-south-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
# optional
RT_SES_CONFIGURATION_SET=magic-links
AWS_SESSION_TOKEN=...
```

`RT_PUBLIC_URL` must be the public site origin: links are built from it.

## 4. Go-live checklist

- [ ] SES identity `mail.example.com` verified in ap-south-1, DKIM and MAIL FROM *Successful*.
- [ ] DKIM CNAMEs, MAIL FROM MX + SPF TXT and DMARC TXT published (section 2).
- [ ] SES production access granted (out of the sandbox) and the daily quota fits launch traffic.
- [ ] Account suppression list on for bounces and complaints.
- [ ] Send-only IAM credentials in the production secret store, not in `.env` on a laptop.
- [ ] Production env sets `RT_MAILER=ses`, `RT_MAIL_FROM`, the AWS keys and `RT_PUBLIC_URL`.
      The server starts, so the startup check passed.
- [ ] A real sign-in from a fresh Gmail and Outlook address lands in the inbox, and the
      headers show SPF/DKIM/DMARC pass.
- [ ] Optional: a bounce/complaint alarm (configuration set → SNS/EventBridge → CloudWatch).
- [ ] After 2–4 weeks of clean DMARC reports: tighten to `p=quarantine`, then `p=reject`.
