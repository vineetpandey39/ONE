# ONE Revenue Pipeline

ALFA and BETA use a local, approval-gated workflow:

1. ALFA finds and packages a qualified lead.
2. Vineet approves the outreach draft. ONE does not send it automatically.
3. After the message is sent, mark the lead as contacted.
4. Paste the client's response. Positive replies generate local proposal,
   service-agreement, and invoice drafts.
5. Record payment with a real transaction reference. Only then does ONE count
   collected revenue and queue BETA.
6. BETA creates a delivery workspace with a plan, QA checklist, and handoff.
7. Mark delivery complete and optionally activate the monthly retainer.

## Optional settings

Set these in `one.env` outside the repository:

```text
ALFA_PAYMENT_LINK=https://your-provider.example/payment-link
ALFA_PAYMENT_WEBHOOK_SECRET=use-a-long-random-local-secret
```

An n8n or payment-provider adapter can call `POST /v1/alfa/payment-webhook`.
The raw JSON body must contain `url`, `amount`, and `reference`. Set the
`x-one-signature` header to the lowercase SHA-256 HMAC of the exact body using
`ALFA_PAYMENT_WEBHOOK_SECRET`.

Revenue shown as collected is payment-confirmed, not inferred from lead value.
Contracts are drafts and must be reviewed before sending.
