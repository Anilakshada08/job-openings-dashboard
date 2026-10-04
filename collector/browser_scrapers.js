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

window.__dump = () => {
  const o = JSON.parse(localStorage.__jobs || "{}");
  const pre = document.createElement("pre");
  pre.textContent = Object.entries(o).map(([u, x]) => [u, x.t, x.c, x.l, x.a, x.s, x.j || "", x.sal || ""].join(" ~ ")).join("\n");
  const art = document.createElement("article");
  art.appendChild(pre);
  document.body.replaceChildren(art);
  return Object.keys(o).length;
};
"scrapers loaded";
