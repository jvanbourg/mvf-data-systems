# MVF Data Systems website

Source for [www.mvfdatasystems.com](https://www.mvfdatasystems.com/): plain HTML/CSS/JS, hosted on **GitHub Pages** from the `main` branch. Pushing to `main` deploys the site (live in about a minute).

## Layout

| Path | Page |
| --- | --- |
| `index.html` | Homepage |
| `business-consulting/` | Business Systems & Operations (Google Ads landing page A) |
| `business-consulting/operations-diagnostic/` | Business Systems Diagnostic |
| `business-consulting/reporting-dashboards/` | Reporting & Business Intelligence |
| `business-consulting/data-integration/` | Data Reconciliation & Systems Integration |
| `healthcare-consulting/` | Healthcare IT & Informatics (Google Ads landing page B) |
| `healthcare-consulting/interoperability/` | Healthcare Data Integration & Interoperability |
| `healthcare-consulting/workflow-optimization/` | Clinical Workflow Optimization |
| `about/`, `case-studies/`, `contact/`, `privacy/` | Supporting pages |
| `about.html`, `services.html`, `expertise.html`, `case-studies.html` | Redirects from the old site's URLs |
| `_partials/` | Shared header, footer, `<head>` tags and contact form |
| `css/style.css` | All styles |
| `js/site-config.js` | **Analytics IDs, Ads conversion label, booking link, form endpoint** |
| `js/main.js` | Mobile nav, attribution capture, form submission, conversion tracking |
| `tools/site.py` | Build and check tool |
| `ads/` | Google Ads campaign definitions and control scripts (not published) |

## Editing workflow

```bash
python3 tools/site.py build   # apply shared partials, version assets, regenerate sitemap.xml
python3 tools/site.py check   # broken links, titles, descriptions, canonicals, H1s, JSON-LD
python3 tools/site.py serve   # preview at http://localhost:8000
git add -A && git commit -m "…" && git push   # deploy
```

Edit page content directly in each `index.html`. To change the header, footer or contact form everywhere, edit the file in `_partials/` and run `build`. Content between `<!-- include:… -->` markers is overwritten by `build`.

## Contact form

Forms post with JavaScript to FormSubmit (`formEndpoint` in `js/site-config.js`), which emails marc.fertout@mvfdatasystems.com. Spam protection: honeypot field plus a minimum fill time. The Google Ads conversion fires only after FormSubmit confirms success.

## Analytics & conversions

Leave IDs blank and nothing loads. To switch on, fill in `ga4Id`, `adsId` and `adsLeadLabel` in `js/site-config.js`, run `build`, and push. No form content is sent to Google. Browsers sending Global Privacy Control don't load the Ads tag.

## Google Ads

See `ads/README.md`.
