// Page scrapers for job sites without a public feed. They run inside the browser on a search-results page,
// read only what the page already shows, and append cards to localStorage.__jobs for that site.
// Usage, per site:
//   1. On the site, run this file once, then: localStorage.__jobs = '{}'
//   2. For each search URL: navigate, then run: await window.__scrape('<site>', '<skillset>')
//      (re-run this file first if the page reloaded and window.__scrape is gone)
//   3. Run: __dump()  -> replaces the page body with one line per job ("url ~ title ~ company ~ location ~ posted ~ skillset ~ type ~ salary")
//      and read it with a page-text tool.

window.__scrape = async (site, skillset) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  await sleep(3000);
  const out = JSON.parse(localStorage.__jobs || "{}");
  const put = (url, j) => { if (url && j.t && !out[url]) out[url] = { ...j, s: skillset }; };
  const lines = (el) => el.innerText.split("\n").map((s) => s.trim()).filter(Boolean);

  if (site === "linkedin") {
    // Cards are rendered lazily, so walk the list and read while scrolling.
    const grab = () => document.querySelectorAll("li[data-occludable-job-id]").forEach((li) => {
      const L = lines(li);
      if (L.length < 3) return;
      const k = (L[1] === L[0] || /with verification$/.test(L[1])) ? 2 : 1;
      put(`https://www.linkedin.com/jobs/view/${li.getAttribute("data-occludable-job-id")}/`, {
        t: L[0].replace(/ with verification$/, ""), c: L[k], l: L[k + 1], a: L.find((s) => / ago$/.test(s)) || "today",
      });
    });
    const n = document.querySelectorAll("li[data-occludable-job-id]").length;
    for (let i = 0; i < n; i++) {
      document.querySelectorAll("li[data-occludable-job-id]")[i]?.scrollIntoView({ block: "center" });
      await sleep(180);
      if (i % 3 === 0) grab();
    }
    grab();
  } else if (site === "dice") {
    const by = {};
    document.querySelectorAll('a[href*="/job-detail/"]').forEach((a) => (by[a.href.split("?")[0]] ||= []).push(a));
    for (const [url, as] of Object.entries(by)) {
      const ta = as.reduce((m, a) => (a.innerText.trim().length > m.innerText.trim().length ? a : m));
      const t = ta.innerText.trim();
      let c = ta;
      for (let i = 0; i < 8 && c.parentElement; i++) { c = c.parentElement; if (lines(c).length >= 4) break; }
      const L = lines(c).filter((s) => !/^(Easy Apply|Apply Now|Apply|Save|Applied|Viewed|Featured)$/i.test(s));
      const [l, w] = (L.find((s) => s.includes("•")) || "").split("•").map((s) => s.trim());
      put(url, { t, c: L.find((s) => s !== t && !s.includes("•") && s.length < 80) || "", l: l || "", a: w || "today",
                 j: (c.innerText.match(/Full-time|Contract|Part-time/i) || [""])[0],
                 sal: (c.innerText.match(/USD [\d,.]+(?: - [\d,.]+)? per (?:year|hour)/) || [""])[0] });
    }
  } else if (site === "indeed") {
    if (/didn.t find any results/i.test(document.body.innerText)) return "no results";
    document.querySelectorAll("div.job_seen_beacon").forEach((card) => {
      const a = card.querySelector("a[data-jk]");
      if (!a) return;
      const q = (s) => (card.querySelector(s) || {}).innerText || "";
      put(`https://www.indeed.com/viewjob?jk=${a.getAttribute("data-jk")}`, {
        t: a.innerText.trim(), c: q('[data-testid="company-name"]'), l: q('[data-testid="text-location"]'),
        a: (card.innerText.match(/Just posted|Today|\d+ days? ago/i) || ["today"])[0],
        j: (card.innerText.match(/Full-time|Contract|Part-time/) || [""])[0],
        sal: (card.innerText.match(/\$[\d,]+(?:\.\d+)?(?: - \$[\d,]+)? (?:a year|an hour)/) || [""])[0],
      });
    });
  } else if (site === "monster") {
    if (/no jobs found/i.test(document.body.innerText)) return "no results";
    document.querySelectorAll('a[href*="/job-openings/"]').forEach((a) => {
      const card = a.closest("article, li, [data-testid]") || a.parentElement;
      const L = lines(card);
      put(a.href.split("?")[0], { t: a.innerText.trim() || L[0], c: L[1] || "", l: L[2] || "",
                                  a: (card.innerText.match(/Today|\d+ (?:hours?|days?) ago/i) || ["today"])[0] });
    });
  }
  localStorage.__jobs = JSON.stringify(out);
  return `${Object.keys(out).length} jobs collected on this site so far`;
};

// Any other site: keep links whose URL matches jobLink (a regex string from sites.json) together with the text of
// the smallest enclosing card. The site agent turns each card's text into title / company / location / posted.
window.__generic = async (jobLink, skillset) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  await sleep(3000);
  for (let i = 0; i < 6; i++) { window.scrollBy(0, 1200); await sleep(400); }  // trigger lazy-loaded results
  const re = new RegExp(jobLink, "i");
  const out = JSON.parse(localStorage.__jobs || "{}");
  const before = Object.keys(out).length;
  for (const a of document.querySelectorAll("a[href]")) {
    const url = a.href.split("#")[0];
    if (!re.test(url) || out[url]) continue;
    let card = a;
    for (let i = 0; i < 6 && card.parentElement; i++) {
      const up = card.parentElement;
      if ([...up.querySelectorAll("a[href]")].filter((x) => re.test(x.href)).length > 1) break;  // next card begins
      card = up;
      if (card.innerText.split("\n").filter(Boolean).length >= 4) break;
    }
    const text = card.innerText.replace(/\s*\n\s*/g, " | ").trim().slice(0, 400);
    if (text.length > 5) out[url] = { card: text, s: skillset };
  }
  localStorage.__jobs = JSON.stringify(out);
  return `${Object.keys(out).length - before} new links, ${Object.keys(out).length} on this site so far`;
};

// Opens each collected job's own page in the background (same site only, max per call) and keeps the sentences
// that matter for filtering: years of experience, remote/hybrid/on-site, contract/full-time, and skill words.
// The collector reads them to level experience, tag work type and confirm the skillset.
window.__enrich = async (max = 40) => {
  const o = JSON.parse(localStorage.__jobs || "{}");
  const todo = Object.keys(o).filter((u) => {
    try { return new URL(u).origin === location.origin && o[u].d === undefined && !u.includes("#"); } catch { return false; }
  }).slice(0, max);
  const KEY = /\d+\s*\+?\s*(?:-|–|to)?\s*\d*\s*\+?\s*(?:years|yrs)|remote|hybrid|on-?site|in[- ]office|contract|c2c|w-?2|1099|full[- ]time|part[- ]time|angular|agile|scrum|jira|sdlc|software development/i;
  // Split into sentences (also where a period runs straight into the next capital, which job pages often do).
  const pick = (text) => text.split(/(?<=[.!?:])\s*(?=[A-Z])|\n+|•/)
    .map((s) => s.replace(/\s+/g, " ").trim()).filter((s) => s.length > 15 && KEY.test(s))
    .map((s) => s.slice(0, 240)).slice(0, 12).join(" ").replace(/[~\r\n]+/g, " ").slice(0, 900);
  let i = 0, read = 0;
  const worker = async () => {
    while (i < todo.length) {
      const u = todo[i++];
      try {
        // LinkedIn loads descriptions separately; its public job-posting fragment has the full text.
        const li = u.match(/linkedin\.com\/jobs\/view\/(\d+)/);
        const res = await fetch(li ? `/jobs-guest/jobs/api/jobPosting/${li[1]}` : u, { credentials: "include" });
        if (!res.ok) continue;
        const doc = new DOMParser().parseFromString(await res.text(), "text/html");
        doc.querySelectorAll("script, style, noscript, svg, header, nav, form").forEach((n) => n.remove());
        // Break the text at block elements so sentences and bullet points stay separate.
        const lined = (doc.body ? doc.body.innerHTML : "").replace(/<(br|\/p|\/li|\/div|\/h\d|li|p)\b[^>]*>/gi, "\n");
        const text = new DOMParser().parseFromString(lined, "text/html").documentElement.textContent || "";
        o[u].d = pick(text) || "-";  // "-" = page read, nothing relevant in it
        read++;
      } catch { /* blocked or cross-site: leave it without a description */ }
    }
  };
  await Promise.all([worker(), worker(), worker(), worker()]);
  localStorage.__jobs = JSON.stringify(o);
  const left = Object.keys(o).filter((u) => o[u].d === undefined).length;
  return `${read} of ${todo.length} job pages read; ${left} without a description`;
};

window.__dump = () => {
  const o = JSON.parse(localStorage.__jobs || "{}");
  const pre = document.createElement("pre");
  pre.textContent = Object.entries(o).map(([u, x]) => (x.card !== undefined
    ? [u, "CARD", x.s, x.card, "DESC", x.d || ""]  // generic scraper: the agent extracts the fields from the card text
    : [u, x.t, x.c, x.l, x.a, x.s, x.j || "", x.sal || "", x.d || ""]).join(" ~ ")).join("\n");
  const art = document.createElement("article");
  art.appendChild(pre);
  document.body.replaceChildren(art);
  return Object.keys(o).length;
};
"scrapers loaded";
