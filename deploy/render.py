#!/usr/bin/env python
"""
Patched apd-core/deploy/render.py - adds CSV + HTML link-check reports.

Builds on the earlier User-Agent/timeout/reason patch. New in this
version: after every run, a report of which links failed (and why)
gets written out in two formats, in two "tiers":

  reports/latest.html   <- always overwritten. This is the file you
  reports/latest.csv       bookmark - the URL never changes, so it
                            always shows the most recent run.

  reports/archive/link-check-report_<timestamp>.html
  reports/archive/link-check-report_<timestamp>.csv
                        <- one dated snapshot per run, so you can look
                           back at previous runs if you want to. Only
                           the 3 most recent snapshots are kept - older
                           ones are deleted automatically every run.

None of this touches index.rst or the .mako template - the reports
are a separate side effect that runs after the existing render step.
"""
import csv
import glob
import io
import logging
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone

import requests
import yaml
from mako.template import Template
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed

session = requests.Session()
session.mount("http://", HTTPAdapter(max_retries=1))
session.mount("https://", HTTPAdapter(max_retries=1))

MAX_WORKERS = 15

# A normal-looking browser User-Agent. Without this, some hosts
# (Cloudflare-fronted sites, gov portals, bot-blocking API gateways)
# return 403/406 to the default `python-requests/x.x.x` UA even
# though the link is genuinely fine.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Seconds to wait before giving up on a slow host. The original used
# a hardcoded `timeout=4`, which is tight for large/slow data portals.
REQUEST_TIMEOUT = 10

# ---- NEW: report rotation settings ----
# How many past runs' reports to keep in reports/archive/ before we
# start deleting the oldest ones. Set to 3 per your request.
KEEP_N_ARCHIVED_REPORTS = 3


def scan_core_data(core_dir, validate_link=False, reports_dir=None):
    """
    Scan and load data entries.

    NEW: `reports_dir` - if provided (and validate_link is True), a
    CSV + HTML report of failing links is written there after
    validation finishes. If left as None, no report is written -
    this keeps the function backward compatible with any other
    caller that doesn't care about reports.
    """
    categories = OrderedDict()  # {catetory: [yaml]}
    category_names = os.listdir(core_dir)

    # ---- Pass 1: load all YAML files from disk (fast, no network) ----
    # (unchanged from the original)
    all_items = []  # list of (category, data_obj) tuples
    for category in sorted(category_names):
        print("Scanned category: ", category)
        if category not in categories:
            categories[category] = list()
        for data_item in sorted(os.listdir(os.path.join(core_dir, category))):
            data_file = os.path.join(core_dir, category, data_item)
            try:
                with open(data_file, 'r') as f:
                    data_obj = yaml.safe_load(f)
                data_obj["_rawFileName"] = data_item
            except Exception as e:
                raise RuntimeError("Failed to read YAML data: {}".format(e))
            all_items.append((category, data_obj))

    if not validate_link:
        # No network work needed - just group by category, in original order.
        for category, data_obj in all_items:
            categories[category].append(data_obj)
        return categories

    # ---- Pass 2: validate all homepage links concurrently ----
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(do_validate_link, data_obj.get("homepage")): (category, data_obj)
            for category, data_obj in all_items
        }

        for future in as_completed(future_to_item):
            category, data_obj = future_to_item[future]
            try:
                result = future.result()
            except Exception as e:
                logging.warning("Unexpected error validating link for {}: {}".format(
                    data_obj.get("_rawFileName"), e))
                result = {"ok": False, "reason": "internal_error: {}".format(e)}

            data_obj["_status"] = result["ok"]
            data_obj["_status_reason"] = result["reason"]
            categories[category].append(data_obj)

    # Concurrent validation scrambles order, so restore alphabetical order
    # to match what the .mako template expects.
    for category in categories:
        categories[category].sort(key=lambda d: d.get("_rawFileName", ""))

    # ---- NEW: write the report, if a destination was given ----
    if reports_dir:
        write_link_check_reports(categories, reports_dir)

    return categories


def write_msg(msg):
    sys.stdout.write(msg)
    sys.stdout.flush()


def do_validate_link(link):
    """
    Validate the accessibility of a homepage link.

    Returns a dict {"ok": bool, "reason": str} - e.g. a 404 comes
    back as {"ok": False, "reason": "http_404"}, a timeout as
    {"ok": False, "reason": "timeout"}, and so on - so the *reason*
    a link failed is preserved all the way through to the report,
    instead of every failure collapsing into a single "FIXME".
    """
    ok = False
    reason = "unknown"

    if link:
        if link.startswith("http://") or link.startswith("https://"):
            try:
                rsp = session.get(
                    link,
                    timeout=REQUEST_TIMEOUT,
                    headers=REQUEST_HEADERS,
                )
                if 400 <= rsp.status_code < 600:
                    ok = False
                else:
                    ok = True
                reason = "http_{}".format(rsp.status_code)
                time.sleep(0.2)  # Be nice to servers
            except requests.exceptions.Timeout:
                ok = False
                reason = "timeout"
            except requests.exceptions.RequestException as e:
                ok = False
                reason = "request_exception: {}".format(e)
            except Exception as e:
                ok = False
                reason = "unexpected_exception: {}".format(e)
        else:
            ok = True
            reason = "non_http_skipped"
    else:
        reason = "no_homepage_field"

    write_msg("Validating {} ... {} ({})\n".format(
        link, "OK" if ok else "FIXME", reason))

    return {"ok": ok, "reason": reason}


# =====================================================================
# NEW: everything below this line is the report-writing addition.
# Nothing above this point is required to read/understand it, but the
# functions above are what feed it (_status and _status_reason).
# =====================================================================

def _collect_failures(categories):
    """
    Walk the categories dict and pull out just the entries that
    failed validation, as a flat list of dicts. Kept as its own
    function so both the CSV and HTML writers can share it instead
    of duplicating the same walk-and-filter loop twice.
    """
    failures = []
    for category, items in categories.items():
        for d in items:
            # `.get("_status", True)` defaults to True (i.e. "not a
            # failure") for any entry that was never validated, e.g.
            # in the unlikely case validate_link ran but this
            # particular entry didn't get a result for some reason.
            if not d.get("_status", True):
                failures.append({
                    "category": category,
                    "file": d.get("_rawFileName", ""),
                    "title": d.get("title", ""),
                    "homepage": d.get("homepage", ""),
                    "reason": d.get("_status_reason", ""),
                })
    return failures


def _write_csv_report(failures, path):
    """Write the failures list out as a CSV file at `path`."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["category", "file", "title", "homepage", "reason"]
        )
        writer.writeheader()
        writer.writerows(failures)


def _write_html_report(failures, path, generated_at):
    """
    Write the failures list out as a small, self-contained HTML page
    at `path`. No external CSS/JS/templating dependency is pulled in
    here on purpose - it's plain inline-styled HTML so the file opens
    correctly on its own, whether that's via GitHub Pages, a raw
    file:// open, or anywhere else.
    """
    # Build the table rows first. html.escape-equivalent by hand here
    # (just replacing the characters that matter for our data, which
    # is URLs/titles/filenames - not full user-supplied HTML) to avoid
    # adding a new dependency just for this.
    def esc(value):
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    rows_html = "\n".join(
        "<tr>"
        "<td>{category}</td>"
        "<td>{file}</td>"
        "<td>{title}</td>"
        "<td><a href=\"{homepage}\">{homepage}</a></td>"
        "<td>{reason}</td>"
        "</tr>".format(
            category=esc(f["category"]),
            file=esc(f["file"]),
            title=esc(f["title"]),
            homepage=esc(f["homepage"]),
            reason=esc(f["reason"]),
        )
        for f in failures
    )

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>apd-core link check report</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; margin: 2rem; }}
  h1 {{ font-size: 1.3rem; }}
  .meta {{ color: #555; margin-bottom: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.9rem; }}
  th {{ background: #f4f4f4; }}
  tr:nth-child(even) {{ background: #fafafa; }}
</style>
</head>
<body>
  <h1>apd-core link check report</h1>
  <p class="meta">Generated {generated_at} UTC &middot; {count} failing link(s)</p>
  <table>
    <thead>
      <tr><th>Category</th><th>File</th><th>Title</th><th>Homepage</th><th>Reason</th></tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
""".format(generated_at=generated_at, count=len(failures), rows=rows_html)

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def _prune_old_archives(archive_dir, keep_n):
    """
    Delete all but the `keep_n` most recent report pairs in
    `archive_dir`. Relies on the timestamp being sortable as a
    string (we use ISO-ish YYYYMMDD-HHMMSS below), so a plain
    alphabetical sort is also a chronological sort.
    """
    # Group files by their timestamp, since each run produces two
    # files (a .csv and an .html) sharing the same timestamp - we
    # want to keep or delete them as a pair, not independently.
    csv_files = sorted(glob.glob(os.path.join(archive_dir, "link-check-report_*.csv")))
    html_files = sorted(glob.glob(os.path.join(archive_dir, "link-check-report_*.html")))

    for file_list in (csv_files, html_files):
        # Keep the last `keep_n` (most recent, since sorted ascending),
        # delete everything before that.
        for old_file in file_list[:-keep_n] if len(file_list) > keep_n else []:
            try:
                os.remove(old_file)
                write_msg("Pruned old report: {}\n".format(old_file))
            except OSError as e:
                logging.warning("Could not delete old report {}: {}".format(old_file, e))


def write_link_check_reports(categories, reports_dir):
    """
    Entry point called from scan_core_data(). Writes:
      - reports_dir/latest.csv, reports_dir/latest.html (always overwritten)
      - reports_dir/archive/link-check-report_<timestamp>.{csv,html}
        (one new dated pair per run, oldest pruned beyond KEEP_N_ARCHIVED_REPORTS)
    """
    archive_dir = os.path.join(reports_dir, "archive")
    os.makedirs(archive_dir, exist_ok=True)

    failures = _collect_failures(categories)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")

    # --- the "latest" pair: stable filenames, always overwritten ---
    # This is what you bookmark - the URL for these two files never
    # changes between runs.
    _write_csv_report(failures, os.path.join(reports_dir, "latest.csv"))
    _write_html_report(failures, os.path.join(reports_dir, "latest.html"), generated_at)

    # --- the dated archive pair for this run ---
    _write_csv_report(
        failures, os.path.join(archive_dir, "link-check-report_{}.csv".format(timestamp))
    )
    _write_html_report(
        failures,
        os.path.join(archive_dir, "link-check-report_{}.html".format(timestamp)),
        generated_at,
    )

    # --- drop anything older than the 3 most recent runs ---
    _prune_old_archives(archive_dir, KEEP_N_ARCHIVED_REPORTS)

    write_msg("Wrote link check report: {} failing link(s) -> {}\n".format(
        len(failures), reports_dir))


if __name__ == "__main__":
    pdir = os.path.dirname(__file__)
    template_file = os.path.join(pdir, "index.mako")
    core_dir = os.path.join(pdir, "..", "core")
    # NEW: where reports get written. Adjust this path to wherever
    # your publishing step (e.g. a GitHub Pages branch checkout)
    # expects to find them - see the accompanying workflow file.
    reports_dir = os.path.join(pdir, "..", "reports")

    categories = scan_core_data(core_dir, validate_link=True, reports_dir=reports_dir)

    with open(template_file, 'r') as f:
        rendered = Template(f.read()).render(categories=categories)
    with open(os.path.join(pdir, "index.rst"), "w") as of:
        of.write(rendered)
        of.write("\n")
