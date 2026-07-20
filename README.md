# MVF Data Systems — Website

Static website for [mvfdatasystems.com](https://mvfdatasystems.com), rebuilt as plain HTML/CSS/JS so it can be edited in Cursor and hosted anywhere. This replaces the IONOS MyWebsite Now builder site (which stays live until you switch the domain over).

## Structure

| File | Purpose |
| --- | --- |
| `index.html` | Home page (hero, overview, contact form) |
| `expertise.html` | Areas of expertise and competitive advantage |
| `services.html` | Data science and IT optimization services |
| `case-studies.html` | Selected client projects |
| `about.html` | Company background and founder bio |
| `css/style.css` | All site styles (colors, layout, components) |
| `js/main.js` | Mobile nav toggle and active-link highlighting |

No build step, no dependencies. Edit the HTML/CSS directly and refresh.

## Preview locally

```bash
python3 -m http.server 8000
```

Then open http://localhost:8000

## Contact form

The form on the home page posts to [Formspree](https://formspree.io). To make it live:

1. Create a free Formspree account and a new form.
2. Replace `YOUR_FORM_ID` in `index.html` with your form's ID.

## Deploying to IONOS

Your domain (`mvfdatasystems.com`) stays with IONOS. Two options:

### Option A — IONOS Deploy Now (recommended)

1. Push this repo to GitHub.
2. Sign in at [ionos.space](https://www.ionos.com/hosting/deploy-now) with your IONOS account and connect the GitHub repo as a "Static project".
3. Every `git push` deploys automatically.
4. In the Deploy Now project settings, assign `mvfdatasystems.com` as the custom domain.

### Option B — Classic webspace via SFTP

1. In the IONOS control panel, set up hosting webspace and find your SFTP credentials.
2. Upload all files in this folder (keeping the `css/` and `js/` structure) to the webspace root.
3. Point the domain at the webspace in IONOS domain settings.

Once the new site is live on the domain, the MyWebsite Now subscription can be cancelled.
