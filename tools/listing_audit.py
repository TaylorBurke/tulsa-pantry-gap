"""Audit the Food Bank's public Food Finder listings for data problems.

Reads the raw Food Finder download (data/raw/fbeo_finder/, fetched by
fetch/fetch_pantries.py) and writes, to reports/ (git-ignored):
  food-finder-audit.csv   one row per finding: listing, check, severity, detail
  food-finder-audit.html  summary, improvement plan and every finding, printable

Each check is a plain rule over the listing fields; nothing is inferred by a
model. Schedule notes that hold a phone number or email are never quoted (they
are reported as "contact details in a schedule note"), and the finder's
contact-name/email fields are not read.

Usage: make audit
"""
import collections
import datetime as dt
import html
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "fbeo_finder"
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)
e = html.escape

DAYS = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
ORDINAL = r"(1st|2nd|3rd|4th|5th|first|second|third|fourth|fifth|last)"
DAYWORD = r"(sun|mon|tue|wed|thu|fri|sat)[a-z]*"
RX_RECUR = re.compile(rf"\b{ORDINAL}\b[^.]*\b({DAYWORD}|month)\b|every other|bi-?weekly", re.I)
RX_ALSO = re.compile(rf"\balso\b[^.]*\b{DAYWORD}\b", re.I)
RX_CHANGE = re.compile(r"\b(beginning|starting|effective|will be|moving to|new (hours|schedule|day))\b", re.I)
RX_APPT = re.compile(r"\bappointment|\bappt\b", re.I)
RX_CONTACT = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b|@[a-z0-9-]+\.[a-z]", re.I)
SCHOOL_NAME = re.compile(r"\b(school|academy|university|tulsa tech|tulsa met)\b", re.I)  # as analysis/pantries.py
RX_RESIDENCY = re.compile(r"must (live|be a resident)|residents? (of|only)|service area|zip codes?|school districts?", re.I)

SEVERITY = {"high": "Wrong for visitors", "medium": "Harder to use", "low": "Housekeeping"}
CHECKS = {  # id: (severity, title, why it matters, fix)
    "impossible_time": ("high", "Hours that can't be right",
                        "A session ends before it starts, runs past 10pm, or lasts over 12 hours, so visitors are shown hours the pantry doesn't keep.",
                        "Correct the start/end time."),
    "copies_disagree": ("high", "Location hours and program hours disagree",
                        "The same pantry carries two sets of hours (on the location and on its program) with no session in common. Depending on the view, visitors see one or the other.",
                        "Keep hours on the program only, or make the two match."),
    "recurrence_only_in_note": ("high", "Monthly schedule only in the note",
                                "The note says e.g. \"third Tuesday\" but the week-of-month field is empty, so the session is published as weekly.",
                                "Set the week-of-month field to match the note."),
    "session_only_in_note": ("high", "A session that exists only in a note",
                             "The note mentions another session (\"also first Sat/month 9-10am\") that isn't in these hours, so searches by day miss it.",
                             "Add it as its own session."),
    "schedule_change_in_note": ("high", "Schedule change announced in a note",
                                "The note says the schedule changed, but the hours fields still show the old one.",
                                "Update the hours, then remove the note."),
    "no_hours": ("high", "Pantry with no hours",
                 "A pantry listing with no hours at all: visitors can't tell when to go, and day/time filters never show it.",
                 "Get hours from the partner, or mark the listing \"call for hours\"."),
    "orphan_hours": ("medium", "Hours attached to a program that isn't published",
                     "Program hours point to a program record the public map doesn't return (inactive, deleted or hidden).",
                     "Re-attach the hours to the live program, or delete them."),
    "duplicate_rows": ("medium", "The same session entered more than once",
                       "Identical hour rows repeated on one listing.",
                       "Delete the copies."),
    "duplicate_listing": ("medium", "Duplicate listings for one site",
                          "Two listings at the same address, often one per program. Map pins stack, and the two can drift apart.",
                          "Merge into one location with several programs (the Finder already supports this, e.g. Iron Gate's meal + pantry listing)."),
    "residency_text_only": ("medium", "Residency rule only in free text",
                            "The program text limits who can be served, but no structured service area is set, so a visitor from outside the area isn't warned by the map.",
                            "Fill in the service-area field."),
    "appointment_only_in_note": ("medium", "\"By appointment\" only in a note",
                                 "Appointment-only hours look like walk-in hours unless the visitor opens the note.",
                                 "Use a structured appointment flag or program type, if the platform has one; otherwise lead the program name with it."),
    "contact_in_note": ("medium", "Contact details in a schedule note",
                        "A phone number or email typed into a schedule note: it can be a person's private number, and it isn't where visitors look for a phone.",
                        "Move it to the phone field (or remove it if it's personal)."),
    "no_hours_school": ("low", "School pantry with no hours",
                        "School pantries serve their own students, so missing hours may be deliberate, but the listing gives the public no way to tell.",
                        "Add hours, or a note that it serves enrolled students only."),
    "no_public_phone": ("low", "No public phone number",
                        "Visitors who need to check hours or eligibility have no number to call.",
                        "Add the pantry's public phone."),
    "ambiguous_weeks": ("low", "\"1st, 2nd, 3rd, 4th\" week setting",
                        "Means either \"every week\" or \"every week except a 5th\". Visitors and tools can't tell which.",
                        "Use weekly (blank) unless the pantry really skips 5th weeks; then say so in the note."),
    "whitespace": ("low", "Stray spaces in name or address",
                   "Leading/trailing spaces break exact-match search and de-duplication.",
                   "Trim the field."),
}


def minutes(ts):
    return int(ts[11:13]) * 60 + int(ts[14:16])


def norm_addr(a):
    a = re.sub(r"[.,]", "", a.lower())
    for k, v in {r"\bwest\b": "w", r"\beast\b": "e", r"\bnorth\b": "n", r"\bsouth\b": "s", r"\bstreet\b": "st",
                 r"\bhighway\b": "hwy", r"\bok\b": "hwy", r"\bavenue\b": "ave"}.items():
        a = re.sub(k, v, a)
    return re.sub(r"\s+", " ", a).strip()


def skey(x):
    """Day + clock times; the API's timestamps carry arbitrary dates, so compare minutes."""
    return x["dayOfWeek"], minutes(x["startTime"]), minutes(x["endTime"])


def weeks_of(x):
    return ",".join(t.strip() for t in f'{x.get("weeksOfMonth") or ""},{x.get("daysOfMonth") or ""}'.split(",") if t.strip())


def session_txt(x):
    wk = ",".join(t.strip() for t in f'{x.get("weeksOfMonth") or ""},{x.get("daysOfMonth") or ""}'.split(",") if t.strip())
    return f'{DAYS[x["dayOfWeek"]]} {x["startTimeDescr"].strip()}–{x["endTimeDescr"].strip()}' + (f" ({wk})" if wk else "")


def audit():
    locs = json.loads((RAW / "locations.json").read_text())
    sch = json.loads((RAW / "schedules.json").read_text())
    fetched = next(m["fetched_at"] for m in json.loads((RAW / "manifest.json").read_text()) if m["file"] == "schedules.json")
    services = {s["locationServiceId"]: s for s in sch["services"]}
    svc_by_loc = collections.defaultdict(list)
    for s in sch["services"]:
        svc_by_loc[s["locationId"]].append(s)
    rows_by_loc = collections.defaultdict(list)
    for x in sch["schedules"]:
        rows_by_loc[x["locationId"]].append(("location hours", x))
    for x in sch["service_schedules"]:
        rows_by_loc[x["locationId"]].append(("program hours", x))

    findings = []

    def add(l, check, detail):
        findings.append({"location_id": l["locationId"], "listing": l["locationName"].strip(),
                         "address": f'{l["address1"].strip()}, {l["city"].strip()}', "check": check,
                         "severity": CHECKS[check][0], "detail": detail})

    for l in locs:
        lid = l["locationId"]
        rows = rows_by_loc[lid]
        for level, x in rows:
            s, t = minutes(x["startTime"]), minutes(x["endTime"])
            if t <= s or t > 22 * 60 or t - s > 12 * 60:
                add(l, "impossible_time", f"{level}: {session_txt(x)}")
            note = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x.get("notes") or "")).strip()
            if not note:
                continue
            quotable = not RX_CONTACT.search(note)
            q = f' — note: "{note[:140]}"' if quotable else ""
            weeks_set = (bool((x.get("weeksOfMonth") or "").strip() or (x.get("daysOfMonth") or "").strip())
                         or bool(x.get("everyOtherWeekInd")))
            right = ""
            if level == "location hours":
                twin = [y for lv, y in rows if lv == "program hours" and skey(y) == skey(x) and weeks_of(y)]
                if twin:
                    right = f" (the program hours have it right: {session_txt(twin[0])})"
            if RX_CHANGE.search(note):
                add(l, "schedule_change_in_note", f"{level}: {session_txt(x)}{q}")
            elif RX_ALSO.search(note):
                add(l, "session_only_in_note", f"{level}: {session_txt(x)}{q}")
            elif RX_RECUR.search(note) and not weeks_set and "weekly" not in note.lower():
                add(l, "recurrence_only_in_note", f"{level}: {session_txt(x)}{q}{right}")
            if RX_APPT.search(note):
                add(l, "appointment_only_in_note", f"{level}: {session_txt(x)}{q}")
            if not quotable:
                add(l, "contact_in_note", f"{level}: {session_txt(x)} (note not quoted here)")
        # one finding per listing for the checks below
        loc_k = {skey(x) for lv, x in rows if lv == "location hours"}
        prg_k = {skey(x) for lv, x in rows if lv == "program hours"}
        if loc_k and prg_k and not loc_k & prg_k:
            lt = "; ".join(sorted({session_txt(x) for lv, x in rows if lv == "location hours"}))
            pt = "; ".join(sorted({session_txt(x) for lv, x in rows if lv == "program hours"}))
            add(l, "copies_disagree", f"location: {lt} | program: {pt}")
        orphans = [x for lv, x in rows if lv == "program hours" and x["locationServiceId"] not in services]
        if orphans:
            np_ = len(svc_by_loc[lid])
            add(l, "orphan_hours", f"{len(orphans)} program-hour rows; listing has {np_ or 'no'} published program{'' if np_ == 1 else 's'}")
        keys = collections.Counter((lv, x.get("locationServiceId"), x["dayOfWeek"], x["startTime"], x["endTime"],
                                    x.get("weeksOfMonth"), x.get("daysOfMonth")) for lv, x in rows)
        dup = sum(c - 1 for c in keys.values() if c > 1)
        if dup:
            add(l, "duplicate_rows", f"{dup} repeated row{'s' if dup > 1 else ''} out of {len(rows)}")
        n_weeks4 = sum(1 for _, x in rows if re.sub(r"\s", "", x.get("weeksOfMonth") or "") == "1st,2nd,3rd,4th")
        if n_weeks4:
            add(l, "ambiguous_weeks", f"{n_weeks4} session{'s' if n_weeks4 > 1 else ''}")
        is_pantry = "Pantry" in (l["foodPrograms"] or "") or any(s["foodProgramTypeDescription"] == "Pantry" for s in svc_by_loc[lid])
        if is_pantry and not rows:
            add(l, "no_hours_school" if SCHOOL_NAME.search(l["locationName"]) else "no_hours", "no location or program hours")
        txt = " ".join(str(s.get(k) or "") for s in svc_by_loc[lid] for k in ["notes", "qualifications", "overview"])
        txt = re.sub(r"<[^>]+>", " ", txt + " " + str(l.get("aboutUs") or "") + " " + str(l.get("notes") or ""))
        structured = bool(l.get("serviceAreas")) or any(s.get("serviceAreas") for s in svc_by_loc[lid])
        m = RX_RESIDENCY.search(txt)
        if m and not structured:
            add(l, "residency_text_only", f'text says "{m.group(0)}"; no service area set')
        if not (l["phone"] or "").strip():
            add(l, "no_public_phone", "phone field empty")
        if l["locationName"] != l["locationName"].strip() or l["address1"] != l["address1"].strip():
            add(l, "whitespace", "name" if l["locationName"] != l["locationName"].strip() else "address")

    groups = collections.defaultdict(list)
    for l in locs:
        groups[(norm_addr(l["address1"]), l["city"].strip().lower())].append(l)
    for g in groups.values():
        if len(g) > 1:
            names = " + ".join(f'{x["locationName"].strip()} [{", ".join(s["serviceName"] for s in svc_by_loc[x["locationId"]]) or "no program"}]'
                               for x in g)
            for x in g:
                add(x, "duplicate_listing", names)

    df = pd.DataFrame(findings)
    df["sev_rank"] = df.severity.map({"high": 0, "medium": 1, "low": 2})
    df = df.sort_values(["sev_rank", "check", "listing"]).drop(columns="sev_rank")
    # one line per listing per check for per-session checks that repeat on every weekday (e.g. a note copied to each day)
    df = df.drop_duplicates(["location_id", "check", "detail"])
    first_note = df.detail.str.extract(r'(note: ".*")', expand=False).fillna(df.detail)
    df = df[~df.assign(k=first_note).duplicated(["location_id", "check", "k"])]
    df.to_csv(OUT / "food-finder-audit.csv", index=False)
    write_html(df, locs, fetched)
    print(f"audit: {len(locs)} listings, {df.location_id.nunique()} with findings, {len(df)} findings -> reports/")
    print(df.groupby(["severity", "check"]).location_id.nunique().to_string())


def write_html(df, locs, fetched):
    when = dt.datetime.fromisoformat(fetched).strftime("%B %-d, %Y")
    by = df.groupby("check").location_id.nunique()
    sev_n = {s: df[df.severity == s].location_id.nunique() for s in SEVERITY}
    copies = int(by.get("copies_disagree", 0))
    summary_rows = "".join(
        f'<tr><td><span class="sev {CHECKS[c][0]}">{SEVERITY[CHECKS[c][0]]}</span></td><td><a href="#{c}">{e(CHECKS[c][1])}</a></td>'
        f'<td class="num">{int(by.get(c, 0))}</td><td>{e(CHECKS[c][3])}</td></tr>'
        for c in CHECKS if by.get(c, 0))
    sections = ""
    for c, (sev, title, why, fix) in CHECKS.items():
        d = df[df.check == c]
        if d.empty:
            continue
        if c == "no_public_phone":
            items = f'<p class="list">{e(", ".join(sorted(d.listing.unique())))}</p>'
        else:
            items = "<ul>" + "".join(f'<li><strong>{e(r.listing)}</strong> <span class="addr">{e(r.address)}</span><br>{e(r.detail)}</li>'
                                     for r in d.itertuples()) + "</ul>"
        k = d.location_id.nunique()
        sections += (f'<section id="{c}"><h3><span class="sev {sev}">{SEVERITY[sev]}</span> {e(title)} '
                     f'<span class="count">{k} listing{"" if k == 1 else "s"}</span></h3>'
                     f'<p>{e(why)} <em>Fix: {e(fix)}</em></p>{items}</section>')
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Food Finder Audit</title>
<style>
:root {{ color-scheme: light; --ink:#1a1714; --ink2:#4a4339; --mut:#6b6358; --rule:#ddd7ca; --paper:#fdfcf8;
  --high:#c42b1c; --medium:#9a5b00; --low:#4a4339; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.5 "Public Sans", system-ui, sans-serif; }}
main {{ max-width: 860px; margin: 0 auto; padding: 32px 16px 64px; }}
h1 {{ font-size: 28px; line-height:1.15; margin: 0 0 6px; }}
h2 {{ font-size: 20px; margin: 32px 0 8px; border-top: 2px solid var(--ink); padding-top: 10px; }}
h3 {{ font-size: 16px; margin: 0 0 4px; }} .by {{ color: var(--mut); font-size: 13px; margin: 0 0 18px; }}
.lede {{ font-size: 17px; color: var(--ink2); }}
.tiles {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(170px,1fr)); gap: 12px; margin: 18px 0; }}
.tile {{ border-top: 3px solid var(--rule); padding-top: 6px; }}
.tile b {{ display:block; font-size: 30px; line-height:1.1; font-variant-numeric: tabular-nums; }}
.tile span {{ color: var(--ink2); font-size: 13px; }}
table {{ width:100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ text-align:left; padding: 6px; border-bottom: 1px solid var(--rule); vertical-align: top; }}
th {{ font-size: 12px; color: var(--mut); border-bottom: 1.5px solid var(--ink); }} .num {{ text-align:right; font-variant-numeric: tabular-nums; }}
.sev {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; white-space: nowrap; }}
.sev.high {{ color: var(--high); }} .sev.medium {{ color: var(--medium); }} .sev.low {{ color: var(--low); }}
section {{ margin: 22px 0; }} section p {{ margin: 0 0 6px; color: var(--ink2); }}
.count {{ font-weight: 400; color: var(--mut); font-size: 13px; }}
ul {{ margin: 6px 0; padding-left: 18px; font-size: 14px; }} li {{ margin-bottom: 6px; break-inside: avoid; }}
.addr {{ color: var(--mut); font-size: 12.5px; }} .list {{ font-size: 13.5px; }} ol.plan li {{ margin-bottom: 8px; }}
.note {{ font-size: 13px; color: var(--mut); }}
@media (max-width: 600px) {{ table {{ font-size: 13px; }} th:last-child, td:last-child {{ display:none; }} }}
@media print {{ body {{ background: #fff; }} main {{ padding: 0; max-width: none; }} @page {{ size: letter; margin: 0.6in; }} a {{ color: inherit; text-decoration: none; }} }}
</style></head><body><main>
<h1>Food Finder listings: data audit</h1>
<p class="by">Prepared by Taylor Burke · checks run on the public Food Finder data as published {when} · {len(locs)} listings within 30 miles of Tulsa</p>
<p class="lede">Most problems come from one pattern: <strong>schedule facts stored where a visitor or a search filter can't use them</strong>.
Hours exist twice (on the location and on each program) and drift apart, and monthly schedules, appointment rules and schedule changes live
in free-text notes while the structured fields say something else. The fixes are mostly one-field edits, and every check is a simple rule
that can be re-run each month to catch new drift.</p>
<div class="tiles">
<div class="tile"><b>{df.location_id.nunique()}</b><span>of {len(locs)} listings have at least one finding</span></div>
<div class="tile"><b>{sev_n["high"]}</b><span>listings show visitors something wrong or missing</span></div>
<div class="tile"><b>{sev_n["medium"]}</b><span>listings are harder to use than they need to be</span></div>
<div class="tile"><b>{sev_n["low"]}</b><span>listings need housekeeping</span></div>
</div>

<h2>Summary</h2>
<table><thead><tr><th>Severity</th><th>Check</th><th class="num">Listings</th><th>Fix</th></tr></thead><tbody>{summary_rows}</tbody></table>

<h2>Improvement plan</h2>
<ol class="plan">
<li><strong>Fix the "wrong for visitors" listings first.</strong> They are short, specific edits (a time, a week-of-month field, one added
session), each listed below with the hours as published. A partner call settles the few that are ambiguous.</li>
<li><strong>Keep hours in one place.</strong> {copies} listing{"" if copies == 1 else "s"} carry location hours and program hours with no
session in common. Pick one home for hours (program level, since the Finder filters by program) and clear the other.</li>
<li><strong>Structured fields over notes.</strong> Week-of-month, appointment-only and service-area rules all have (or need) a field. A short
data-entry guide for partner agencies, with "if your note says X, set field Y" examples from this audit, would stop most of this at the source.</li>
<li><strong>One location, many programs.</strong> Merge same-address duplicates into a single location with several programs, as some listings already do.</li>
<li><strong>Add a "last verified" date and a recurring check.</strong> A quarterly confirm-your-hours prompt to partners, plus this audit run
monthly against the public data, would catch drift before visitors do. The audit is a script and can produce this report on a schedule.</li>
</ol>
<p class="note">Method: every check is a fixed rule over the public listing fields (described in each section). Notes containing a phone number or
email are not quoted. "Location hours" are the hours on the location record; "program hours" are the hours on one of its programs. Findings are
leads to confirm, not verdicts: a pantry may have a reason for an unusual setting.</p>

<h2>Every finding</h2>
{sections}
</main></body></html>"""
    (OUT / "food-finder-audit.html").write_text(page)


if __name__ == "__main__":
    audit()
