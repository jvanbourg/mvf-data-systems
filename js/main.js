/* MVF Data Systems: navigation, attribution capture, analytics, lead form. */
(function () {
  "use strict";

  var CFG = window.MVF_CONFIG || {};
  var ATTR_KEY = "mvf_attribution";
  var ATTR_FIELDS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "gbraid", "wbraid"];

  /* ---------- Storage helpers (never throw) ---------- */
  function readStore(key) {
    try { return JSON.parse(window.sessionStorage.getItem(key) || "null"); } catch (e) { return null; }
  }
  function writeStore(key, val) {
    try { window.sessionStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* ignore */ }
  }

  /* ---------- Attribution: first touch within the browsing session ---------- */
  function captureAttribution() {
    var params;
    try { params = new URLSearchParams(window.location.search); } catch (e) { return readStore(ATTR_KEY) || {}; }
    var found = {};
    var any = false;
    ATTR_FIELDS.forEach(function (k) {
      var v = params.get(k);
      if (v) { found[k] = v.slice(0, 200); any = true; }
    });
    var existing = readStore(ATTR_KEY);
    if (any || !existing) {
      found.landing_page = window.location.pathname;
      found.referrer = (document.referrer || "").slice(0, 200);
      writeStore(ATTR_KEY, found);
      return found;
    }
    return existing;
  }

  /* ---------- Google tag (only when IDs are configured) ---------- */
  var gpc = navigator.globalPrivacyControl === true;
  var adsEnabled = !!(CFG.adsId && !gpc);
  var tagId = CFG.ga4Id || (adsEnabled ? CFG.adsId : "");

  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }

  if (tagId) {
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(tagId);
    document.head.appendChild(s);
    gtag("js", new Date());
    if (CFG.ga4Id) gtag("config", CFG.ga4Id);
    if (adsEnabled) gtag("config", CFG.adsId);
  }

  function trackLead(practice, txnId) {
    // Only ever called after the form service confirms delivery.
    // No form content (names, emails, messages) is sent to Google.
    if (CFG.ga4Id) {
      gtag("event", "generate_lead", { practice: practice, form_location: window.location.pathname });
    }
    if (adsEnabled && CFG.adsLeadLabel) {
      gtag("event", "conversion", {
        send_to: CFG.adsId + "/" + CFG.adsLeadLabel,
        transaction_id: txnId
      });
    }
  }

  /* ---------- Lead form ---------- */
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function setError(field, msg) {
    var input = field.querySelector("input, textarea");
    var err = field.querySelector(".field-error");
    if (input) input.setAttribute("aria-invalid", msg ? "true" : "false");
    if (err) err.textContent = msg || "";
  }

  function validate(form) {
    var ok = true;
    var first = null;
    form.querySelectorAll(".field[data-validate]").forEach(function (field) {
      var input = field.querySelector("input, textarea");
      var v = (input.value || "").trim();
      var msg = "";
      if (input.required && !v) msg = "Please fill in this field.";
      else if (input.type === "email" && v && !EMAIL_RE.test(v)) msg = "Please enter a valid email address.";
      else if (input.name === "message" && v && v.length < 10) msg = "Please add a little more detail.";
      setError(field, msg);
      if (msg) { ok = false; if (!first) first = input; }
    });
    if (first) first.focus();
    return ok;
  }

  function initForm(form, attribution) {
    var loadedAt = Date.now();
    var status = form.querySelector(".form-status");
    var button = form.querySelector("button[type=submit]");
    var practice = form.getAttribute("data-practice") || "general";
    var sending = false;

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (sending || form.classList.contains("is-sent")) return;
      status.className = "form-status";
      status.textContent = "";

      if (!validate(form)) return;

      // Spam checks: honeypot filled, or submitted implausibly fast.
      var hp = form.querySelector("input[name=_honey]");
      if ((hp && hp.value) || Date.now() - loadedAt < 2500) {
        status.className = "form-status is-error";
        status.textContent = "Sorry, your request could not be sent. Please email marc.fertout@mvfdatasystems.com directly.";
        return;
      }

      var data = new FormData(form);
      ATTR_FIELDS.concat(["landing_page", "referrer"]).forEach(function (k) {
        if (attribution[k]) data.set(k, attribution[k]);
      });
      data.set("page", window.location.pathname);
      var txnId = "mvf-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
      data.set("request_id", txnId);

      sending = true;
      button.disabled = true;
      var label = button.textContent;
      button.textContent = "Sending…";

      fetch(CFG.formEndpoint || form.action, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(Object.fromEntries(data.entries()))
      })
        .then(function (res) {
          return res.json().catch(function () { return {}; }).then(function (body) {
            var ok = res.ok && (body.success === true || body.success === "true");
            if (!ok) throw new Error(body.message || "HTTP " + res.status);
            return body;
          });
        })
        .then(function () {
          form.classList.add("is-sent");
          status.className = "form-status is-success";
          status.innerHTML = "<strong>Thank you. Your request has been sent.</strong> Marc will reply by email, usually within one business day.";
          status.setAttribute("tabindex", "-1");
          status.focus();
          trackLead(practice, txnId);
        })
        .catch(function () {
          status.className = "form-status is-error";
          status.textContent = "Sorry, something went wrong and your request was not sent. Please try again, or email marc.fertout@mvfdatasystems.com directly.";
        })
        .then(function () {
          sending = false;
          button.disabled = false;
          button.textContent = label;
        });
    });

    form.querySelectorAll(".field[data-validate] input, .field[data-validate] textarea").forEach(function (input) {
      input.addEventListener("blur", function () {
        if (input.getAttribute("aria-invalid") === "true") validate(form);
      });
    });
  }

  /* ---------- Boot ---------- */
  document.addEventListener("DOMContentLoaded", function () {
    // Mobile navigation
    var toggle = document.querySelector(".nav-toggle");
    var links = document.getElementById("primary-nav");
    if (toggle && links) {
      toggle.addEventListener("click", function () {
        var open = links.classList.toggle("open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && links.classList.contains("open")) {
          links.classList.remove("open");
          toggle.setAttribute("aria-expanded", "false");
          toggle.focus();
        }
      });
    }

    // Optional booking link
    if (CFG.bookingUrl) {
      document.documentElement.classList.add("has-booking");
      document.querySelectorAll("[data-booking]").forEach(function (a) { a.href = CFG.bookingUrl; });
    }

    var attribution = captureAttribution();
    document.querySelectorAll("form.lead-form").forEach(function (f) { initForm(f, attribution); });
  });
})();
