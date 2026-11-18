#!/usr/bin/env python3
"""MVF Data Systems: Google Ads control tool.

Run with the bundled environment:  ads/.venv/bin/python ads/mvf_ads.py <command>

Setup & inspection
  doctor                 Check tooling, credentials and API access
  accounts               List Google Ads accounts these credentials can reach
  audit                  Account details, billing, campaigns, conversions, landing pages
  geo                    Resolve target counties via Google's geo-target API (and show the DMA for comparison)
  research               Keyword Planner historical metrics -> ads/reports/keyword_research.csv (needs Basic API access)
  lint                   Offline check of campaigns.yaml (character limits, duplicates)
  plan                   Offline dry run: build every operation without calling the API

Build (always PAUSED, never duplicates)
  apply [--validate-only]   Create anything in campaigns.yaml missing from the account
  conversion-setup [--validate-only]   Create the lead-form conversion action, enable auto-tagging
  conversion-tag [--write]  Show the Ads tag ID + conversion label; --write puts them in js/site-config.js

Day-to-day control
  status                 Campaign status, budgets, ad approvals
  report [--days N]      Performance by campaign / ad group / keyword / search term -> ads/reports/
  pause <business|healthcare|all>
  enable <business|healthcare> --i-approve-spend
  set-budget <business|healthcare> <monthly_usd> --i-approve-spend
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC_PATH = HERE / "campaigns.yaml"
STATE_PATH = HERE / "state.json"
REPORTS = HERE / "reports"
SITE_CONFIG = ROOT / "js" / "site-config.js"

LIMITS = dict(headline=30, description=90, path=15, sitelink_text=25, sitelink_desc=35, callout=25, snippet_value=25)


# --------------------------------------------------------------------------- spec

LOCAL_PATH = HERE / "account.local.yaml"   # gitignored: customer ID stays out of the public repo


def load_spec() -> dict:
    spec = yaml.safe_load(SPEC_PATH.read_text())
    if LOCAL_PATH.exists():
        spec["account"].update(yaml.safe_load(LOCAL_PATH.read_text()) or {})
    return spec


def daily_micros(spec: dict, monthly_usd: float) -> int:
    daily = round(monthly_usd / spec["defaults"]["days_per_month"], 2)
    return int(round(daily * 100)) * 10_000


def lint(spec: dict) -> list[str]:
    errs = []
    seen_kw = {}
    for c in spec["campaigns"]:
        for s in c["sitelinks"]:
            if len(s["text"]) > LIMITS["sitelink_text"]:
                errs.append(f"{c['key']}: sitelink text too long: {s['text']!r}")
            for k in ("d1", "d2"):
                if len(s[k]) > LIMITS["sitelink_desc"]:
                    errs.append(f"{c['key']}: sitelink description too long: {s[k]!r}")
        for t in c["callouts"]:
            if len(t) > LIMITS["callout"]:
                errs.append(f"{c['key']}: callout too long: {t!r}")
        for v in c["snippets"]["values"]:
            if len(v) > LIMITS["snippet_value"]:
                errs.append(f"{c['key']}: snippet value too long: {v!r}")
        for ag in c["ad_groups"]:
            ad = ag["ad"]
            hs, ds = ad["headlines"], ad["descriptions"]
            if not 3 <= len(hs) <= 15:
                errs.append(f"{ag['name']}: needs 3-15 headlines, has {len(hs)}")
            if not 2 <= len(ds) <= 4:
                errs.append(f"{ag['name']}: needs 2-4 descriptions, has {len(ds)}")
            if len({h.lower() for h in hs}) != len(hs):
                errs.append(f"{ag['name']}: duplicate headlines")
            for h in hs:
                if len(h) > LIMITS["headline"]:
                    errs.append(f"{ag['name']}: headline {len(h)} chars: {h!r}")
            for d in ds:
                if len(d) > LIMITS["description"]:
                    errs.append(f"{ag['name']}: description {len(d)} chars: {d!r}")
            for p in ("path1", "path2"):
                if len(ad.get(p, "")) > LIMITS["path"]:
                    errs.append(f"{ag['name']}: {p} too long")
            for mt in ("exact", "phrase"):
                for kw in ag["keywords"].get(mt, []):
                    key = (kw.lower(), mt)
                    if key in seen_kw:
                        errs.append(f"duplicate keyword [{mt}] {kw!r} in {ag['name']} and {seen_kw[key]}")
                    seen_kw[key] = ag["name"]
                    if kw != kw.lower():
                        errs.append(f"{ag['name']}: keyword should be lowercase: {kw!r}")
    return errs


# --------------------------------------------------------------------------- client

def adc_path() -> Path:
    return Path(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or Path.home() / ".config/gcloud/application_default_credentials.json")


def get_client(spec: dict, offline: bool = False):
    from google.ads.googleads.client import GoogleAdsClient

    if offline:
        from google.auth.credentials import AnonymousCredentials
        return GoogleAdsClient(credentials=AnonymousCredentials(), use_proto_plus=True)
    cfg = {"use_proto_plus": True}
    yaml_cfg = HERE / "google-ads.yaml"
    if yaml_cfg.exists():
        return GoogleAdsClient.load_from_storage(str(yaml_cfg))
    cfg["use_application_default_credentials"] = True
    login = str(spec["account"].get("login_customer_id") or "").replace("-", "")
    if login:
        cfg["login_customer_id"] = login
    return GoogleAdsClient.load_from_dict(cfg)


def customer_id(spec: dict) -> str:
    cid = str(spec["account"].get("customer_id") or "").replace("-", "")
    if not re.fullmatch(r"\d{10}", cid):
        sys.exit("Set customer_id (10 digits) in ads/account.local.yaml first, e.g.  customer_id: \"1234567890\". Run `accounts` to see options.")
    return cid


def search(client, cid: str, query: str):
    ga = client.get_service("GoogleAdsService")
    return list(ga.search(customer_id=cid, query=query))


def explain_error(ex) -> str:
    try:
        from google.ads.googleads.errors import GoogleAdsException
        if isinstance(ex, GoogleAdsException):
            msgs = [f"{e.error_code} {e.message}" for e in ex.failure.errors]
            text = "\n  ".join(msgs)
            hint = ""
            if "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION" in text:
                hint = ("\nHint: the Google Cloud project only has Test access. In Cloud Console open "
                        "APIs & Services > Google Ads API > 'Upgrade access level' and request Explorer access.")
            elif "USER_PERMISSION_DENIED" in text:
                hint = "\nHint: the signed-in Google user can't access this customer ID (or set login_customer_id for a manager account)."
            elif "NOT_ENABLED" in text or "SERVICE_DISABLED" in text:
                hint = "\nHint: enable the Google Ads API in the Google Cloud project."
            return f"Google Ads API error (request {ex.request_id}):\n  {text}{hint}"
    except Exception:
        pass
    return f"{type(ex).__name__}: {ex}"


# --------------------------------------------------------------------------- lookups

def resolve_geo(client, cid, canonical_names):
    names = ", ".join("'" + n.replace("'", "\\'") + "'" for n in canonical_names)
    rows = search(client, cid,
        "SELECT geo_target_constant.resource_name, geo_target_constant.id, geo_target_constant.name, "
        "geo_target_constant.canonical_name, geo_target_constant.target_type, geo_target_constant.status "
        f"FROM geo_target_constant WHERE geo_target_constant.canonical_name IN ({names})")
    found = {r.geo_target_constant.canonical_name: r.geo_target_constant for r in rows}
    missing = [n for n in canonical_names if n not in found]
    if missing:
        sys.exit(f"Geo targets not found via API: {missing}")
    return [found[n] for n in canonical_names]


def resolve_languages(client, cid, codes):
    q = ", ".join(f"'{c}'" for c in codes)
    rows = search(client, cid, f"SELECT language_constant.resource_name, language_constant.code FROM language_constant WHERE language_constant.code IN ({q})")
    return [r.language_constant.resource_name for r in rows]


def snapshot(client, cid) -> dict:
    """Read everything we manage from the account (non-removed only)."""
    s = {"budgets": {}, "campaigns": {}, "criteria": {}, "ad_groups": {}, "keywords": {}, "ads": {}, "assets": {}, "conversion_actions": {}}
    for r in search(client, cid, "SELECT campaign_budget.resource_name, campaign_budget.name, campaign_budget.amount_micros FROM campaign_budget WHERE campaign_budget.status != 'REMOVED'"):
        s["budgets"][r.campaign_budget.name] = r.campaign_budget.resource_name
    for r in search(client, cid, "SELECT campaign.resource_name, campaign.id, campaign.name, campaign.status, campaign.campaign_budget, campaign_budget.amount_micros FROM campaign WHERE campaign.status != 'REMOVED'"):
        s["campaigns"][r.campaign.name] = dict(rn=r.campaign.resource_name, id=r.campaign.id, status=r.campaign.status.name,
                                               budget_rn=r.campaign.campaign_budget, daily_micros=r.campaign_budget.amount_micros)
    for r in search(client, cid, "SELECT campaign.name, campaign_criterion.type, campaign_criterion.negative, campaign_criterion.keyword.text, "
                    "campaign_criterion.keyword.match_type, campaign_criterion.location.geo_target_constant, campaign_criterion.language.language_constant "
                    "FROM campaign_criterion WHERE campaign.status != 'REMOVED'"):
        cc = r.campaign_criterion
        bucket = s["criteria"].setdefault(r.campaign.name, set())
        t = cc.type_.name
        if t == "LOCATION":
            bucket.add(("LOCATION", cc.location.geo_target_constant))
        elif t == "LANGUAGE":
            bucket.add(("LANGUAGE", cc.language.language_constant))
        elif t == "KEYWORD" and cc.negative:
            bucket.add(("NEG", cc.keyword.text.lower(), cc.keyword.match_type.name))
    for r in search(client, cid, "SELECT campaign.name, ad_group.resource_name, ad_group.name, ad_group.status, ad_group.cpc_bid_micros FROM ad_group WHERE ad_group.status != 'REMOVED' AND campaign.status != 'REMOVED'"):
        s["ad_groups"][(r.campaign.name, r.ad_group.name)] = r.ad_group.resource_name
    for r in search(client, cid, "SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type "
                    "FROM ad_group_criterion WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE "
                    "AND ad_group_criterion.status != 'REMOVED' AND ad_group.status != 'REMOVED'"):
        s["keywords"].setdefault((r.campaign.name, r.ad_group.name), set()).add(
            (r.ad_group_criterion.keyword.text.lower(), r.ad_group_criterion.keyword.match_type.name))
    for r in search(client, cid, "SELECT campaign.name, ad_group.name, ad_group_ad.resource_name, ad_group_ad.status, "
                    "ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.policy_summary.approval_status "
                    "FROM ad_group_ad WHERE ad_group_ad.status != 'REMOVED' AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'"):
        hs = frozenset(h.text for h in r.ad_group_ad.ad.responsive_search_ad.headlines)
        s["ads"].setdefault((r.campaign.name, r.ad_group.name), []).append(
            dict(rn=r.ad_group_ad.resource_name, headlines=hs, status=r.ad_group_ad.status.name,
                 approval=r.ad_group_ad.policy_summary.approval_status.name))
    for r in search(client, cid, "SELECT campaign.name, campaign_asset.field_type, asset.sitelink_asset.link_text, asset.callout_asset.callout_text, "
                    "asset.structured_snippet_asset.header FROM campaign_asset WHERE campaign_asset.status != 'REMOVED'"):
        ft = r.campaign_asset.field_type.name
        text = {"SITELINK": r.asset.sitelink_asset.link_text, "CALLOUT": r.asset.callout_asset.callout_text,
                "STRUCTURED_SNIPPET": r.asset.structured_snippet_asset.header}.get(ft)
        if text:
            s["assets"].setdefault(r.campaign.name, set()).add((ft, text))
    for r in search(client, cid, "SELECT conversion_action.resource_name, conversion_action.id, conversion_action.name, conversion_action.status, "
                    "conversion_action.type, conversion_action.category, conversion_action.primary_for_goal FROM conversion_action "
                    "WHERE conversion_action.status != 'REMOVED'"):
        ca = r.conversion_action
        s["conversion_actions"][ca.name] = dict(rn=ca.resource_name, id=ca.id, type=ca.type_.name, category=ca.category.name,
                                                primary=ca.primary_for_goal, status=ca.status.name)
    return s


def empty_snapshot():
    return {"budgets": {}, "campaigns": {}, "criteria": {}, "ad_groups": {}, "keywords": {}, "ads": {}, "assets": {}, "conversion_actions": {}}


# --------------------------------------------------------------------------- build operations

class Builder:
    def __init__(self, client, cid):
        self.client, self.cid = client, cid
        self.ops, self.labels = [], []
        self._tmp = 0
        self.E = client.enums

    def tmp(self, collection):
        self._tmp -= 1
        return f"customers/{self.cid}/{collection}/{self._tmp}"

    def op(self, label):
        o = self.client.get_type("MutateOperation")
        self.ops.append(o)
        self.labels.append(label)
        return o


def build_operations(client, cid, spec, snap, geo_rns, lang_rns):
    b = Builder(client, cid)
    E = b.E
    for c in spec["campaigns"]:
        name = c["name"]
        existing = snap["campaigns"].get(name)
        if existing:
            camp_rn = existing["rn"]
        else:
            budget_name = f"{name} | budget"
            budget_rn = snap["budgets"].get(budget_name)
            if not budget_rn:
                budget_rn = b.tmp("campaignBudgets")
                bud = b.op(f"budget  {budget_name}  ${daily_micros(spec, c['monthly_budget_usd'])/1e6:.2f}/day").campaign_budget_operation.create
                bud.resource_name = budget_rn
                bud.name = budget_name
                bud.amount_micros = daily_micros(spec, c["monthly_budget_usd"])
                bud.delivery_method = E.BudgetDeliveryMethodEnum.STANDARD
                bud.explicitly_shared = False
            camp_rn = b.tmp("campaigns")
            cp = b.op(f"campaign  {name}  (PAUSED)").campaign_operation.create
            cp.resource_name = camp_rn
            cp.name = name
            cp.status = E.CampaignStatusEnum.PAUSED
            cp.advertising_channel_type = E.AdvertisingChannelTypeEnum.SEARCH
            cp.campaign_budget = budget_rn
            client.copy_from(cp.manual_cpc, client.get_type("ManualCpc"))
            ns = spec["defaults"]["networks"]
            cp.network_settings.target_google_search = bool(ns["google_search"])
            cp.network_settings.target_search_network = bool(ns["search_partners"])
            cp.network_settings.target_content_network = bool(ns["display"])
            cp.network_settings.target_partner_search_network = False
            cp.geo_target_type_setting.positive_geo_target_type = E.PositiveGeoTargetTypeEnum.PRESENCE
            cp.geo_target_type_setting.negative_geo_target_type = E.NegativeGeoTargetTypeEnum.PRESENCE
            cp.contains_eu_political_advertising = E.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
            if c.get("final_url_suffix"):
                cp.final_url_suffix = c["final_url_suffix"]

        have = snap["criteria"].get(name, set())
        for g in geo_rns:
            if ("LOCATION", g) not in have:
                cc = b.op(f"  location  {g}").campaign_criterion_operation.create
                cc.campaign = camp_rn
                cc.location.geo_target_constant = g
        for lr in lang_rns:
            if ("LANGUAGE", lr) not in have:
                cc = b.op(f"  language  {lr}").campaign_criterion_operation.create
                cc.campaign = camp_rn
                cc.language.language_constant = lr
        negs = []
        for src in (spec["shared_negatives"], c.get("negatives", {})):
            negs += [(t, "BROAD") for t in src.get("broad", [])] + [(t, "PHRASE") for t in src.get("phrase", [])]
        for text, mt in dict.fromkeys(negs):
            if ("NEG", text.lower(), mt) not in have:
                cc = b.op(f"  negative  [{mt.lower()}] {text}").campaign_criterion_operation.create
                cc.campaign = camp_rn
                cc.negative = True
                cc.keyword.text = text
                cc.keyword.match_type = getattr(E.KeywordMatchTypeEnum, mt)

        have_assets = snap["assets"].get(name, set())
        def add_asset(ft, key, fill, label):
            if (ft, key) in have_assets:
                return
            arn = b.tmp("assets")
            a = b.op(f"  asset  {label}").asset_operation.create
            a.resource_name = arn
            fill(a)
            ca = b.op(f"  link  {ft.lower()} -> campaign").campaign_asset_operation.create
            ca.asset = arn
            ca.campaign = camp_rn
            ca.field_type = getattr(E.AssetFieldTypeEnum, ft)
        for s in c["sitelinks"]:
            def fill(a, s=s):
                a.sitelink_asset.link_text = s["text"]
                a.sitelink_asset.description1 = s["d1"]
                a.sitelink_asset.description2 = s["d2"]
                a.final_urls.append(s["url"])
            add_asset("SITELINK", s["text"], fill, f"sitelink {s['text']}")
        for t in c["callouts"]:
            def fill(a, t=t):
                a.callout_asset.callout_text = t
            add_asset("CALLOUT", t, fill, f"callout {t}")
        sn = c["snippets"]
        def fill_sn(a, sn=sn):
            a.structured_snippet_asset.header = sn["header"]
            a.structured_snippet_asset.values.extend(sn["values"])
        add_asset("STRUCTURED_SNIPPET", sn["header"], fill_sn, f"snippet {sn['header']}")

        for ag in c["ad_groups"]:
            key = (name, ag["name"])
            ag_rn = snap["ad_groups"].get(key)
            if not ag_rn:
                ag_rn = b.tmp("adGroups")
                g = b.op(f"  ad group  {ag['name']}  max CPC ${ag['max_cpc_usd']:.2f}").ad_group_operation.create
                g.resource_name = ag_rn
                g.name = ag["name"]
                g.campaign = camp_rn
                g.status = E.AdGroupStatusEnum.ENABLED
                g.type_ = E.AdGroupTypeEnum.SEARCH_STANDARD
                g.cpc_bid_micros = int(round(ag["max_cpc_usd"] * 100)) * 10_000
            have_kw = snap["keywords"].get(key, set())
            for mt in ("exact", "phrase"):
                for kw in ag["keywords"].get(mt, []):
                    if (kw.lower(), mt.upper()) in have_kw:
                        continue
                    k = b.op(f"    keyword  [{mt}] {kw}").ad_group_criterion_operation.create
                    k.ad_group = ag_rn
                    k.status = E.AdGroupCriterionStatusEnum.ENABLED
                    k.keyword.text = kw
                    k.keyword.match_type = getattr(E.KeywordMatchTypeEnum, mt.upper())
            ad = ag["ad"]
            want = frozenset(ad["headlines"])
            ads_here = snap["ads"].get(key, [])
            if any(x["headlines"] == want for x in ads_here):
                continue
            if ads_here:
                print(f"note: {ag['name']} already has a different RSA; adding the new version alongside it (pause the old one after review).")
            aga = b.op(f"    responsive search ad  ({len(ad['headlines'])} headlines, {len(ad['descriptions'])} descriptions)").ad_group_ad_operation.create
            aga.ad_group = ag_rn
            aga.status = E.AdGroupAdStatusEnum.ENABLED
            aga.ad.final_urls.append(c["final_url"])
            rsa = aga.ad.responsive_search_ad
            for h in ad["headlines"]:
                t = client.get_type("AdTextAsset"); t.text = h; rsa.headlines.append(t)
            for d in ad["descriptions"]:
                t = client.get_type("AdTextAsset"); t.text = d; rsa.descriptions.append(t)
            rsa.path1 = ad.get("path1", "")
            rsa.path2 = ad.get("path2", "")
    return b


def build_conversion_op(client, cid, spec, snap):
    b = Builder(client, cid)
    E = b.E
    conv = spec["conversion_action"]
    if conv["name"] in snap["conversion_actions"]:
        return b
    ca = b.op(f"conversion action  {conv['name']}").conversion_action_operation.create
    ca.name = conv["name"]
    ca.type_ = E.ConversionActionTypeEnum.WEBPAGE
    ca.category = getattr(E.ConversionActionCategoryEnum, conv["category"])
    ca.status = E.ConversionActionStatusEnum.ENABLED
    ca.counting_type = getattr(E.ConversionActionCountingTypeEnum, conv["counting"])
    ca.primary_for_goal = bool(conv["primary"])
    ca.value_settings.default_value = 0
    ca.value_settings.always_use_default_value = True
    return b


def execute(client, cid, builder, validate_only):
    if not builder.ops:
        print("Nothing to create: account already matches campaigns.yaml.")
        return
    print(f"{len(builder.ops)} operation(s):")
    for l in builder.labels:
        print("  " + l)
    ga = client.get_service("GoogleAdsService")
    req = client.get_type("MutateGoogleAdsRequest")
    req.customer_id = cid
    req.mutate_operations.extend(builder.ops)
    req.validate_only = validate_only
    req.partial_failure = False
    ga.mutate(request=req)
    print("VALIDATED OK (nothing was changed)." if validate_only else "Created. All campaigns remain PAUSED.")


# --------------------------------------------------------------------------- commands

def cmd_lint(spec, args):
    errs = lint(spec)
    for e in errs:
        print("ERROR:", e)
    n_kw = sum(len(ag["keywords"].get(m, [])) for c in spec["campaigns"] for ag in c["ad_groups"] for m in ("exact", "phrase"))
    print(f"lint: {len(errs)} error(s); {len(spec['campaigns'])} campaigns, "
          f"{sum(len(c['ad_groups']) for c in spec['campaigns'])} ad groups, {n_kw} keywords")
    for c in spec["campaigns"]:
        d = daily_micros(spec, c["monthly_budget_usd"]) / 1e6
        print(f"  {c['name']}: ${c['monthly_budget_usd']}/month -> ${d:.2f}/day average")
    return 1 if errs else 0


def cmd_plan(spec, args):
    if lint(spec):
        return cmd_lint(spec, args)
    client = get_client(spec, offline=True)
    fake = "0000000000"
    geo = [f"geoTargetConstants/<{n.split(',')[0]}>" for n in spec["defaults"]["locations"]]
    langs = ["languageConstants/<en>"]
    b = build_operations(client, fake, spec, empty_snapshot(), geo, langs)
    c = build_conversion_op(client, fake, spec, empty_snapshot())
    for l in c.labels + b.labels:
        print(l)
    print(f"plan: {len(b.ops) + len(c.ops)} operations would be sent to an empty account (offline; nothing contacted).")
    return 0


def cmd_doctor(spec, args):
    ok = True
    print("google-ads library:", __import__("importlib.metadata").metadata.version("google-ads"))
    g = shutil.which("gcloud")
    print("gcloud:", g or "NOT INSTALLED  (brew install --cask google-cloud-sdk)")
    p = adc_path()
    print("Application Default Credentials:", "found" if p.exists() else f"MISSING ({p})")
    if p.exists():
        try:
            info = json.loads(p.read_text())
            print("  type:", info.get("type"), "| quota project:", info.get("quota_project_id", "(none)"))
        except Exception:
            pass
    else:
        ok = False
    print("customer_id (ads/account.local.yaml):", spec["account"].get("customer_id") or "(not set)")
    errs = lint(spec)
    print("campaigns.yaml lint:", "OK" if not errs else f"{len(errs)} error(s)")
    if not ok:
        print("\nNot connected yet. See 'Connecting' in ads/README.md.")
        return 1
    try:
        client = get_client(spec)
        res = client.get_service("CustomerService").list_accessible_customers()
        print("API access: OK, accessible customers:", ", ".join(r.split("/")[-1] for r in res.resource_names) or "(none)")
    except Exception as ex:
        print(explain_error(ex))
        return 1
    return 0


def cmd_accounts(spec, args):
    client = get_client(spec)
    res = client.get_service("CustomerService").list_accessible_customers()
    for rn in res.resource_names:
        cid = rn.split("/")[-1]
        try:
            r = search(client, cid, "SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone, customer.manager, customer.test_account FROM customer LIMIT 1")[0].customer
            print(f"{cid}  {r.descriptive_name!r}  {r.currency_code}  {r.time_zone}  manager={r.manager}  test={r.test_account}")
        except Exception as ex:
            print(f"{cid}  (cannot read: {explain_error(ex).splitlines()[0]})")
    return 0


def check_url(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mvf-ads-check"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.geturl()
    except Exception as ex:
        return getattr(ex, "code", "ERR"), str(ex)


def cmd_audit(spec, args):
    client = get_client(spec)
    cid = customer_id(spec)
    c = search(client, cid, "SELECT customer.descriptive_name, customer.currency_code, customer.time_zone, customer.auto_tagging_enabled, "
               "customer.test_account, customer.status FROM customer LIMIT 1")[0].customer
    print(f"Account {cid}: {c.descriptive_name!r}  currency={c.currency_code}  tz={c.time_zone}  status={c.status.name}  "
          f"auto-tagging={'on' if c.auto_tagging_enabled else 'OFF'}  test={c.test_account}")
    if c.currency_code != spec["account"]["currency"] or c.time_zone != spec["account"]["time_zone"]:
        print(f"  WARNING: expected {spec['account']['currency']} / {spec['account']['time_zone']}")
    try:
        bills = search(client, cid, "SELECT billing_setup.id, billing_setup.status, billing_setup.payments_account_info.payments_account_name FROM billing_setup")
        if not bills:
            print("Billing: NO billing setup. Ads cannot serve until billing is added in the Google Ads UI.")
        for r in bills:
            print(f"Billing: {r.billing_setup.status.name}  {r.billing_setup.payments_account_info.payments_account_name}")
    except Exception as ex:
        print("Billing: could not read:", explain_error(ex).splitlines()[0])
    snap = snapshot(client, cid)
    print(f"\nCampaigns ({len(snap['campaigns'])}):")
    for n, v in snap["campaigns"].items():
        print(f"  {v['id']}  {n}  {v['status']}  ${v['daily_micros']/1e6:.2f}/day")
    wanted = {x["name"] for x in spec["campaigns"]}
    for n in snap["campaigns"]:
        if n not in wanted and any(w.split("|")[1].strip().lower() in n.lower() for w in wanted):
            print(f"  WARNING: {n!r} looks similar to a managed campaign; check for duplicates.")
    print(f"\nConversion actions ({len(snap['conversion_actions'])}):")
    for n, v in snap["conversion_actions"].items():
        print(f"  {v['id']}  {n}  type={v['type']}  category={v['category']}  primary={v['primary']}  {v['status']}")
    ga4 = [n for n, v in snap["conversion_actions"].items() if v["type"].startswith("GOOGLE_ANALYTICS_4")]
    print("GA4 link:", "GA4 conversions imported, so GA4 is linked" if ga4 else "no GA4 conversions imported (link in Google Ads > Tools > Linked accounts if wanted)")
    print("\nLanding pages:")
    for camp in spec["campaigns"]:
        st, final = check_url(camp["final_url"])
        print(f"  {st}  {camp['final_url']}")
        for s in camp["sitelinks"]:
            st, _ = check_url(s["url"])
            print(f"  {st}  {s['url']}")
    return 0


def cmd_geo(spec, args):
    client = get_client(spec)
    cid = customer_id(spec)
    for g in resolve_geo(client, cid, spec["defaults"]["locations"]):
        print(f"TARGET  {g.resource_name}  {g.canonical_name}  type={g.target_type}  status={g.status.name}")
    rows = search(client, cid, "SELECT geo_target_constant.resource_name, geo_target_constant.canonical_name, geo_target_constant.target_type "
                  "FROM geo_target_constant WHERE geo_target_constant.target_type = 'DMA Region' AND geo_target_constant.name LIKE 'Los Angeles%'")
    for r in rows:
        print(f"NOT USED  {r.geo_target_constant.resource_name}  {r.geo_target_constant.canonical_name}  (DMA: also covers Ventura, "
              "San Bernardino, Riverside and other counties; broader than LA + Orange)")
    return 0


def cmd_research(spec, args):
    client = get_client(spec)
    cid = customer_id(spec)
    geo = [g.resource_name for g in resolve_geo(client, cid, spec["defaults"]["locations"])]
    lang = resolve_languages(client, cid, spec["defaults"]["languages"])[0]
    kws = sorted({kw for c in spec["campaigns"] for ag in c["ad_groups"] for m in ("exact", "phrase") for kw in ag["keywords"].get(m, [])})
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    req.customer_id = cid
    req.keywords.extend(kws)
    req.geo_target_constants.extend(geo)
    req.language = lang
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    try:
        resp = svc.generate_keyword_historical_metrics(request=req)
    except Exception as ex:
        print(explain_error(ex))
        print("\nKeyword Planner via API needs Basic or Standard access. Use the UI workflow in ads/README.md instead.")
        return 1
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "keyword_research.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["keyword", "avg_monthly_searches", "competition", "low_top_of_page_bid_usd", "high_top_of_page_bid_usd"])
        for r in resp.results:
            m = r.keyword_metrics
            w.writerow([r.text, m.avg_monthly_searches, m.competition.name,
                        f"{m.low_top_of_page_bid_micros/1e6:.2f}", f"{m.high_top_of_page_bid_micros/1e6:.2f}"])
    print(f"Wrote {out} ({len(resp.results)} keywords, LA + Orange County, English, Google Search).")
    return 0


def write_state(client, cid):
    snap = snapshot(client, cid)
    state = {
        "customer_id": cid,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "campaigns": {n: {"id": v["id"], "resource_name": v["rn"], "status": v["status"], "budget_resource_name": v["budget_rn"],
                          "daily_budget_usd": v["daily_micros"] / 1e6} for n, v in snap["campaigns"].items()},
        "ad_groups": {f"{k[0]} :: {k[1]}": rn for k, rn in snap["ad_groups"].items()},
        "conversion_actions": {n: {"id": v["id"], "resource_name": v["rn"]} for n, v in snap["conversion_actions"].items()},
    }
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")
    print(f"State saved to {STATE_PATH.relative_to(ROOT)}")


def cmd_apply(spec, args):
    errs = lint(spec)
    if errs:
        return cmd_lint(spec, args)
    client = get_client(spec)
    cid = customer_id(spec)
    try:
        geo = [g.resource_name for g in resolve_geo(client, cid, spec["defaults"]["locations"])]
        langs = resolve_languages(client, cid, spec["defaults"]["languages"])
        snap = snapshot(client, cid)
        b = build_operations(client, cid, spec, snap, geo, langs)
        execute(client, cid, b, args.validate_only)
        if not args.validate_only:
            write_state(client, cid)
    except Exception as ex:
        print(explain_error(ex))
        return 1
    return 0


def cmd_conversion_setup(spec, args):
    client = get_client(spec)
    cid = customer_id(spec)
    try:
        snap = snapshot(client, cid)
        execute(client, cid, build_conversion_op(client, cid, spec, snap), args.validate_only)
        c = search(client, cid, "SELECT customer.auto_tagging_enabled FROM customer LIMIT 1")[0].customer
        if not c.auto_tagging_enabled:
            from google.api_core import protobuf_helpers
            op = client.get_type("CustomerOperation")
            op.update.resource_name = f"customers/{cid}"
            op.update.auto_tagging_enabled = True
            client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, op.update._pb))
            client.get_service("CustomerService").mutate_customer(customer_id=cid, operation=op, validate_only=args.validate_only)
            print("Auto-tagging (gclid):", "would be enabled" if args.validate_only else "enabled")
        else:
            print("Auto-tagging (gclid): already on")
        if not args.validate_only:
            write_state(client, cid)
    except Exception as ex:
        print(explain_error(ex))
        return 1
    return 0


def cmd_conversion_tag(spec, args):
    client = get_client(spec)
    cid = customer_id(spec)
    name = spec["conversion_action"]["name"]
    rows = search(client, cid, "SELECT conversion_action.name, conversion_action.tag_snippets FROM conversion_action "
                  f"WHERE conversion_action.name = '{name}' AND conversion_action.status != 'REMOVED'")
    if not rows:
        print("Conversion action not found. Run conversion-setup first.")
        return 1
    send_to = None
    for snip in rows[0].conversion_action.tag_snippets:
        m = re.search(r"'send_to':\s*'(AW-\d+)/([\w-]+)'", snip.event_snippet)
        if m:
            send_to = m.groups()
            break
    if not send_to:
        print("Could not find send_to in the tag snippets.")
        return 1
    ads_id, label = send_to
    print(f"Google Ads tag ID: {ads_id}\nConversion label:  {label}")
    if args.write:
        txt = SITE_CONFIG.read_text()
        txt = re.sub(r'adsId:\s*"[^"]*"', f'adsId: "{ads_id}"', txt)
        txt = re.sub(r'adsLeadLabel:\s*"[^"]*"', f'adsLeadLabel: "{label}"', txt)
        SITE_CONFIG.write_text(txt)
        print(f"Updated {SITE_CONFIG.relative_to(ROOT)}. Next: python3 tools/site.py build && commit && push.")
    return 0


def find_campaign(spec, snap, key):
    names = [c["name"] for c in spec["campaigns"] if key in ("all", c["key"])]
    if not names:
        sys.exit(f"Unknown campaign {key!r}; use business, healthcare or all.")
    out = []
    for n in names:
        if n not in snap["campaigns"]:
            print(f"{n}: not in account (run apply)")
            continue
        out.append((n, snap["campaigns"][n]))
    return out


def set_campaign_status(client, cid, rn, status):
    from google.api_core import protobuf_helpers
    op = client.get_type("CampaignOperation")
    op.update.resource_name = rn
    op.update.status = getattr(client.enums.CampaignStatusEnum, status)
    client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, op.update._pb))
    client.get_service("CampaignService").mutate_campaigns(customer_id=cid, operations=[op])


def cmd_status(spec, args):
    client = get_client(spec)
    cid = customer_id(spec)
    snap = snapshot(client, cid)
    for c in spec["campaigns"]:
        v = snap["campaigns"].get(c["name"])
        if not v:
            print(f"{c['name']}: not created")
            continue
        d = v["daily_micros"] / 1e6
        print(f"{c['name']}  [{v['status']}]  id={v['id']}  ${d:.2f}/day (~${d*spec['defaults']['days_per_month']:.0f}/month)")
        for ag in c["ad_groups"]:
            key = (c["name"], ag["name"])
            ads = snap["ads"].get(key, [])
            appr = ", ".join(f"{a['status']}/{a['approval']}" for a in ads) or "no ads"
            print(f"   {ag['name']}: {len(snap['keywords'].get(key, ()))} keywords; ads: {appr}")
    return 0


def cmd_pause(spec, args):
    client = get_client(spec)
    cid = customer_id(spec)
    for n, v in find_campaign(spec, snapshot(client, cid), args.campaign):
        set_campaign_status(client, cid, v["rn"], "PAUSED")
        print(f"PAUSED  {n}")
    return 0


def cmd_enable(spec, args):
    if not args.i_approve_spend:
        sys.exit("Refusing: enabling starts ad spend. Re-run with --i-approve-spend once you have reviewed the campaign.")
    client = get_client(spec)
    cid = customer_id(spec)
    if args.campaign == "all":
        sys.exit("Enable campaigns one at a time.")
    for n, v in find_campaign(spec, snapshot(client, cid), args.campaign):
        d = v["daily_micros"] / 1e6
        print(f"About to ENABLE {n}: average ${d:.2f}/day (~${d*spec['defaults']['days_per_month']:.0f}/month).")
        if sys.stdin.isatty():
            if input("Type ENABLE to confirm: ").strip() != "ENABLE":
                sys.exit("Cancelled.")
        set_campaign_status(client, cid, v["rn"], "ENABLED")
        print(f"ENABLED  {n}")
    return 0


def cmd_set_budget(spec, args):
    if not args.i_approve_spend:
        sys.exit("Refusing: budget changes affect spend. Re-run with --i-approve-spend.")
    from google.api_core import protobuf_helpers
    client = get_client(spec)
    cid = customer_id(spec)
    for n, v in find_campaign(spec, snapshot(client, cid), args.campaign):
        new = daily_micros(spec, args.monthly_usd)
        op = client.get_type("CampaignBudgetOperation")
        op.update.resource_name = v["budget_rn"]
        op.update.amount_micros = new
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, op.update._pb))
        client.get_service("CampaignBudgetService").mutate_campaign_budgets(customer_id=cid, operations=[op])
        print(f"{n}: ${v['daily_micros']/1e6:.2f}/day -> ${new/1e6:.2f}/day (~${args.monthly_usd}/month). Update campaigns.yaml to match.")
    return 0


def cmd_report(spec, args):
    client = get_client(spec)
    cid = customer_id(spec)
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=args.days - 1)
    when = f"segments.date BETWEEN '{start}' AND '{end}'"
    M = ("metrics.impressions, metrics.clicks, metrics.ctr, metrics.average_cpc, metrics.cost_micros, "
         "metrics.conversions, metrics.conversions_from_interactions_rate, metrics.cost_per_conversion")
    levels = {
        "campaigns": (f"SELECT campaign.name, campaign.status, {M} FROM campaign WHERE {when} AND campaign.status != 'REMOVED'",
                      lambda r: [r.campaign.name, "", "", ""]),
        "ad_groups": (f"SELECT campaign.name, ad_group.name, {M} FROM ad_group WHERE {when} AND ad_group.status != 'REMOVED'",
                      lambda r: [r.campaign.name, r.ad_group.name, "", ""]),
        "keywords": (f"SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, {M} "
                     f"FROM keyword_view WHERE {when}",
                     lambda r: [r.campaign.name, r.ad_group.name, r.ad_group_criterion.keyword.text, r.ad_group_criterion.keyword.match_type.name]),
        "search_terms": (f"SELECT campaign.name, ad_group.name, search_term_view.search_term, {M} FROM search_term_view WHERE {when}",
                         lambda r: [r.campaign.name, r.ad_group.name, r.search_term_view.search_term, ""]),
    }
    REPORTS.mkdir(exist_ok=True)
    stamp = end.isoformat()
    head = ["campaign", "ad_group", "keyword_or_search_term", "match_type", "impressions", "clicks", "ctr",
            "avg_cpc_usd", "cost_usd", "conversions", "conv_rate", "cost_per_conversion_usd"]
    tables = {}
    try:
        for lvl, (q, dims) in levels.items():
            rows = []
            for r in search(client, cid, q):
                m = r.metrics
                rows.append(dims(r) + [m.impressions, m.clicks, f"{m.ctr:.2%}", f"{m.average_cpc/1e6:.2f}", f"{m.cost_micros/1e6:.2f}",
                                       f"{m.conversions:.1f}", f"{m.conversions_from_interactions_rate:.2%}",
                                       f"{m.cost_per_conversion/1e6:.2f}" if m.conversions else ""])
            rows.sort(key=lambda x: -float(x[8]))
            tables[lvl] = rows
            with (REPORTS / f"{stamp}_{lvl}.csv").open("w", newline="") as f:
                w = csv.writer(f); w.writerow(head); w.writerows(rows)
    except Exception as ex:
        print(explain_error(ex))
        return 1
    md = [f"# MVF Google Ads report: {start} to {end}\n",
          "Conversions = primary conversion actions (website consultation requests). Review each lead before calling it qualified.\n",
          "## Business vs Healthcare\n", "| Campaign | Impr. | Clicks | CTR | Avg CPC | Cost | Conv. | Conv. rate | Cost / conv. |", "|---|---|---|---|---|---|---|---|---|"]
    for r in tables["campaigns"]:
        md.append(f"| {r[0]} | {r[4]} | {r[5]} | {r[6]} | ${r[7]} | ${r[8]} | {r[9]} | {r[10]} | {('$' + r[11]) if r[11] else '-'} |")
    md += ["\n## Top search terms by cost\n", "| Campaign | Search term | Clicks | Cost | Conv. |", "|---|---|---|---|---|"]
    for r in tables["search_terms"][:25]:
        md.append(f"| {r[0].split('|')[1].strip()} | {r[2]} | {r[5]} | ${r[8]} | {r[9]} |")
    md += ["\n## Keywords\n", "| Ad group | Keyword | Match | Impr. | Clicks | CTR | Cost | Conv. |", "|---|---|---|---|---|---|---|---|"]
    for r in tables["keywords"]:
        md.append(f"| {r[1]} | {r[2]} | {r[3].lower()} | {r[4]} | {r[5]} | {r[6]} | ${r[8]} | {r[9]} |")
    out = REPORTS / f"{stamp}_report.md"
    out.write_text("\n".join(md) + "\n")
    print("\n".join(md[:5 + len(tables['campaigns'])]))
    print(f"\nSaved {out.relative_to(ROOT)} and CSVs in ads/reports/")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("doctor", "accounts", "audit", "geo", "research", "lint", "plan", "status"):
        sub.add_parser(n)
    p = sub.add_parser("apply"); p.add_argument("--validate-only", action="store_true")
    p = sub.add_parser("conversion-setup"); p.add_argument("--validate-only", action="store_true")
    p = sub.add_parser("conversion-tag"); p.add_argument("--write", action="store_true")
    p = sub.add_parser("report"); p.add_argument("--days", type=int, default=30)
    p = sub.add_parser("pause"); p.add_argument("campaign")
    p = sub.add_parser("enable"); p.add_argument("campaign"); p.add_argument("--i-approve-spend", action="store_true")
    p = sub.add_parser("set-budget"); p.add_argument("campaign"); p.add_argument("monthly_usd", type=float); p.add_argument("--i-approve-spend", action="store_true")
    args = ap.parse_args()
    spec = load_spec()
    fn = globals()["cmd_" + args.cmd.replace("-", "_")]
    try:
        sys.exit(fn(spec, args))
    except Exception as ex:
        if type(ex).__name__ == "DefaultCredentialsError":
            sys.exit("Not signed in to Google yet. See 'Connecting' in ads/README.md, then run `doctor`.")
        sys.exit(explain_error(ex))


if __name__ == "__main__":
    main()
