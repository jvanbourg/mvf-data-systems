# First 30 days after enabling

Goal: cost per **qualified** consultation request. Budgets stay at $600 / $400 per month. No budget increases or new match types without explicit approval.

Run `ads/.venv/bin/python ads/mvf_ads.py report --days 7` (or ask Claude) on each check-in.

## Days 1–3: make sure it works
- `status`: every ad approved, both campaigns serving.
- Impressions > 0 within 24h. If none: check billing, ad approval, and whether max CPC is too low (look at "Search lost IS (rank)" in the UI).
- Submit one real test form. Confirm the email arrives and the conversion appears in Google Ads (Goals → Conversions; it can take up to 24h).

## Days 3–10: search-term hygiene (most important)
- Read every search term in `*_search_terms.csv`. Add negatives for job seekers, students, software shoppers, DIY/tutorial searches, specific ERP/EHR vendor-partner searches Marc isn't positioned for, and anything outside LA/OC intent.
- Add negatives to `campaigns.yaml` and re-run `apply` so the file stays the source of truth.
- Pause keywords with 0 relevant search terms after ~100 impressions.

## Days 10–20: bids and relevance
- Keywords with good CTR (>5%) and relevant terms but low impression share → raise max CPC 10–20% (with approval).
- Keywords spending > ~$60 with no conversion and weak terms → lower bid or pause.
- Compare RSA asset ratings (UI: Ads → Assets). Replace "Low" headlines in `campaigns.yaml`.
- If one healthcare ad group gets nearly all traffic, consider folding the others into it.

## Days 20–30: lead quality
- Marc rates each lead: qualified / not qualified, with the reason. Leads carry utm_term (keyword) and gclid in the email.
- Compute cost per qualified lead per campaign. Shift budget toward the better one only with approval.
- Landing pages: if clicks are healthy but conversion rate < 2%, test a shorter form intro, move the form higher, or use specific subpages (e.g. /business-consulting/reporting-dashboards/) as ad-group final URLs.
- With ≥15 conversions, discuss Maximize Conversions / Target CPA.

## Do not
- Enable broad match, Search Partners or Display without a reason and approval.
- Judge performance on fewer than ~10 clicks per keyword.
- Count clicks or page views as success.
