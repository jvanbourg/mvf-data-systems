# Google Ads: MVF Data Systems

Two Search campaigns, defined in `campaigns.yaml` and managed with `mvf_ads.py`. Everything is created **PAUSED**. Nothing spends money until you run `enable … --i-approve-spend`.

```bash
PY=ads/.venv/bin/python
$PY ads/mvf_ads.py doctor            # is everything connected?
$PY ads/mvf_ads.py status            # campaigns, budgets, ad approvals
$PY ads/mvf_ads.py report --days 7   # performance -> ads/reports/
$PY ads/mvf_ads.py pause all         # emergency stop
```

Or just ask Claude in this folder: "how are the ads doing?", "pause the healthcare campaign", "add 'payroll software' as a negative".

## What gets built

| | Campaign A | Campaign B |
| --- | --- | --- |
| Name | MVF \| Business Consulting \| Los Angeles | MVF \| Healthcare IT \| Los Angeles |
| Budget | $600/month = **$19.74/day** average | $400/month = **$13.16/day** average |
| Landing page | /business-consulting/ | /healthcare-consulting/ |
| Ad groups | Business Systems & Operations · Reporting & Business Intelligence · Data & ERP Integration | Healthcare IT & Clinical Workflow · Health Informatics & Data · HL7 FHIR & Interoperability |
| Starting max CPC | $5.00 | $6.00 |

Shared settings: Search only (no Search Partners, no Display), **Manual CPC**, English, Los Angeles County + Orange County (counties resolved through Google's geo-target API, not the larger LA DMA), location option **Presence**, exact and phrase match only, campaign-level negatives, sitelinks, callouts, structured snippets, UTM tagging through the final URL suffix.

Daily budgets use Google's 30.4-day month. Google can spend up to 2× the daily budget on a given day and balances it over the month, so this is an average target, not a hard cap. Google's billing rules describe a monthly charging limit of about 30.4 × the average daily budget, but budget changes mid-month and Google's own policies affect the actual total. Watch `report` rather than assuming an exact figure.

**Why Manual CPC:** with no conversion history, automated strategies (Maximize Conversions, Target CPA) have nothing to learn from and tend to overspend while exploring. After about 15–30 recorded consultation requests, consider switching to Maximize Conversions with a target CPA.

**Bids:** $5/$6 are conservative starting points chosen *without* Keyword Planner data. Check them against real estimates (below) before enabling.

## Connecting (one-time)

Google sunset developer tokens in Sept 2026. API access now comes from a Google Cloud project plus a Google sign-in.

1. **Google Ads account.** Marc needs a Google Ads account (ads.google.com) with billing set up, created in **USD** and **(GMT-08:00) Pacific Time**. Currency and time zone can't be changed later. Note the 10-digit customer ID and save it in `ads/account.local.yaml` as `customer_id: "1234567890"` (gitignored; the repo is public).
2. **Google Cloud project.** At console.cloud.google.com, create a project (e.g. `mvf-ads`), then **APIs & Services → Library → Google Ads API → Enable**.
3. **OAuth client.** APIs & Services → OAuth consent screen (External, add yourself as a test user), then Credentials → Create credentials → OAuth client ID → **Desktop app**. Download the JSON to `~/.config/mvf/client_secret.json` (outside this repo).
4. **Sign in** with the Google account that can access the Ads account:
   ```bash
   gcloud auth application-default login \
     --client-id-file="$HOME/.config/mvf/client_secret.json" \
     --scopes=https://www.googleapis.com/auth/adwords,https://www.googleapis.com/auth/cloud-platform
   ```
5. **Production access.** In Cloud Console → Google Ads API → **Upgrade access level** → request **Explorer** (usually automatic). Explorer can create campaigns. Keyword Planner via API needs **Basic** (requires brand verification).
6. Check: `ads/.venv/bin/python ads/mvf_ads.py doctor` then `accounts`.

## Building the campaigns

```bash
$PY ads/mvf_ads.py audit                        # account, billing, existing campaigns, landing pages
$PY ads/mvf_ads.py geo                          # confirm LA + Orange County targets
$PY ads/mvf_ads.py conversion-setup             # lead-form conversion action + auto-tagging
$PY ads/mvf_ads.py conversion-tag --write       # put AW- ID + label in js/site-config.js
python3 tools/site.py build && git commit -am "Enable Ads conversion tag" && git push
$PY ads/mvf_ads.py apply --validate-only        # Google validates everything, changes nothing
$PY ads/mvf_ads.py apply                        # create (PAUSED); re-running never duplicates
$PY ads/mvf_ads.py status
```

`apply` is idempotent: it reads the account, compares with `campaigns.yaml`, and creates only what is missing. To change ad copy, edit the YAML and re-run. The new ad is added next to the old one; pause the old one after review. IDs are saved to `ads/state.json` (local, not committed).

## Keyword research without API access

If `research` reports insufficient access, use the UI: Google Ads → Tools → **Keyword Planner** → *Get search volume and forecasts* → paste the keywords from `campaigns.yaml` → Locations: *Los Angeles County* and *Orange County, California* → Language English → Network Google. Download the CSV to `ads/reports/keyword_research.csv` and ask Claude to review bids and keywords against it.

## Activating (only after review)

1. `status`: confirm every ad is APPROVED (or ELIGIBLE), budgets and keywords are right, and billing is active (`audit`).
2. Submit one test form on the live site and confirm the email arrives.
3. `$PY ads/mvf_ads.py enable business --i-approve-spend` (and/or `healthcare`).
4. Check `report --days 1` the next day.

To stop: `$PY ads/mvf_ads.py pause all`. To change spend: `set-budget business 800 --i-approve-spend` (monthly USD).

## Conversion tracking

- Primary conversion: **MVF | Consultation request (website form)**, website conversion, category *Submit lead form*, one per click.
- Fires from `js/main.js` **only after FormSubmit confirms delivery**, with a unique `transaction_id` so Google de-duplicates. No form content is sent to Google.
- Page views, button clicks and form starts are not conversions.
- Avoid double counting: if GA4 is linked later, don't import GA4's `generate_lead` as a *primary* Ads conversion. Keep it secondary or don't import it.
- gclid, gbraid, wbraid and UTM values are captured into each lead email so Marc can see which campaign and keyword produced it. To track lead *quality* later, record qualified leads and import them as an offline conversion keyed on gclid.

## Official MCP server (optional, read-only reporting in Claude)

Once step 4 above works:
```bash
claude mcp add google-ads --scope project -e GOOGLE_CLOUD_PROJECT=<project-id> -- pipx run --spec google-ads-mcp==0.0.6 google-ads-mcp
```
It can query reports and manage assets/labels, but it can't create campaigns, ad groups, budgets or bids. `mvf_ads.py` does that.
