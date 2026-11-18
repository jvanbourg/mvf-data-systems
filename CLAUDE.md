# MVF Data Systems: working notes for Claude

Website and Google Ads for MVF Data Systems (Marc Fertout's consulting practice, Los Angeles). The owner manages both from this folder via Claude Code.

## Website
- Static HTML on GitHub Pages (repo `jvanbourg/mvf-data-systems`, branch `main`, custom domain www.mvfdatasystems.com). **Pushing to `main` deploys to production.** Confirm with the user before pushing.
- After any page edit: `python3 tools/site.py build && python3 tools/site.py check`. Fix all errors before committing.
- Shared header/footer/form/head live in `_partials/`; never hand-edit content between `<!-- include:x -->` markers in pages (build overwrites it). New pages need an entry in `CRUMBS` in `tools/site.py`.
- Jekyll (`_config.yml`) excludes `tools/`, `ads/`, README.md, CLAUDE.md, flyer-assets/ from the public site. Keep it that way.
- Preview: `python3 tools/site.py serve`.

## Content rules (from the owner's brief)
- Source of truth for Marc's experience: his two CVs ("CV Marc FERTOUT 202610 eng 1pj.pdf", "CV Marc V Fertout HI 202611.pdf" in ~/Downloads). Do not invent clients, results, statistics, testimonials, certifications or prices.
- No public prices. "Book a Free Consultation" / "Request a Quote". First conversation is free; diagnostics are paid.
- Never present Marc as a CPA, accountant, auditor, bookkeeper, tax adviser or fractional CFO. Don't imply US healthcare regulatory or US EHR experience.
- Program budgets are client program sizes, never MVF revenue.
- Phone number: not on the site or in ads until the owner confirms which number to use (CVs list two).
- Healthcare forms must keep the "no PHI" notice.

## Google Ads
- Everything lives in `ads/`; see `ads/README.md`. Campaign definitions: `ads/campaigns.yaml`. Control: `ads/.venv/bin/python ads/mvf_ads.py <command>`.
- **Never enable campaigns, raise budgets, or change bids without explicit approval from the user in the current conversation.** Creating/updating in PAUSED state is fine.
- Credentials live outside the repo (ADC via gcloud; `ads/google-ads.yaml` is gitignored). Never print or commit tokens.
