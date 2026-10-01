<!-- SAIPEN KNOWLEDGE CARD v1 -->
kind: convention
scope: usage-limits,resets
trigger: adding or changing manual/redeemable reset offers (Codex credits, ZCode Coding Plan cards, Claude campaigns)
status: active
evidence: architecture.md
supersedes: none

# Manual reset offers are a separate concept from automatic window resets

A redeemable reset offer (`model.ResetOffer` on `UsageSnapshot.reset_offers`) is never an automatic refill (`UsageWindow.resets_at_epoch`), never quota capacity, and never wallet credit. Presentation sources are `reset_offer_rows` / `manual_reset_count` / `banked_reset_count` (quantity-aware), all independent of the ordinary hide-zero / hide-unusable filters and of Shift; only an explicit settings-hide excludes an account. Owning offers never flips `account_usable_now` and never enters `reset_candidates`. Expiry reads through the ONE shared `format_offer_expiry` ("expires in ...", never "resets in ...").

Why:
Codex reset credits used to vanish from the topbar the moment their exhausted account was filtered away, and the reset state was Codex-only (`banked_resets`). The generic model makes the same presentation serve every provider, and the semantic split stops manual cards from masquerading as automatic refills or free capacity.

Provider facts that must not be re-derived:
- Codex: `rateLimitResetCredits` maps to offers; a bare `availableCount` is ONE aggregate offer with `quantity=N` and empty `offer_id` — never fabricated card identities. Direct activation is proven and stays wired.
- ZCode: Coding Plan reset cards live at `https://zcode.z.ai/api/v1/coding-plan/reset/status` with `Authorization: Bearer <zcodejwttoken>` + `X-Bigmodel-Authorization: <oauth:zai|bigmodel access_token>` + `Bigmodel-Target-Type: PERSONAL` (proven from the installed client bundle; the plan API key is NOT used). `expire_at` is epoch ms and only future entries are cards. Auth failure / missing signed-in session is state `unavailable` in `provider_metadata["reset_cards"]` — NEVER rendered as "zero resets". Consumption (`POST .../use`) stays unwired until independently proven live; the UI opens the vendor page instead.
- Claude: no first-party payload today carries offer metadata; a generic defensive parser (`claude._campaign_offers`) requires EXPLICIT availability (null is not available) and no redemption is claimed (`redeemable_in_fastprompter=False`).
