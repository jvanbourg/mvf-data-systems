/*
 * MVF Data Systems: site configuration.
 *
 * Fill these in as accounts are set up. Anything left blank is simply
 * switched off; nothing loads or fires until a value is present.
 *
 *   ga4Id         Google Analytics 4 measurement ID, e.g. "G-XXXXXXXXXX"
 *   adsId         Google Ads tag ID, e.g. "AW-123456789"
 *   adsLeadLabel  Conversion label of the "Consultation request" conversion
 *                 action, e.g. "AbCdEfGhIjKlMnOp" (from Google Ads, or from
 *                 `python ads/mvf_ads.py conversion-tag`)
 *   bookingUrl    Scheduling link (Calendly, Google Calendar booking page…).
 *                 When set, "Schedule a call" buttons appear automatically.
 *   formEndpoint  Where consultation requests are delivered (FormSubmit).
 */
window.MVF_CONFIG = {
  ga4Id: "",
  adsId: "AW-18583552195",
  adsLeadLabel: "xuiDCMDFkrsdEMOBqp1F",
  bookingUrl: "",
  formEndpoint: "https://formsubmit.co/ajax/marc.fertout@mvfdatasystems.com"
};
