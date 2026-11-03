#!/usr/bin/env python
"""
apd-core/deploy/render.py

Renders core/*/*.yaml into deploy/index.rst (the README for
awesome-public-datasets).

Two modes:

  python deploy/render.py
      FAST mode (used on every deploy). Makes no network requests. The
      OK / FIXME icon on each entry comes from deploy/link-status.json,
      the result of the most recent nightly link check. If that file is
      missing, every entry simply shows the OK icon.

  python deploy/render.py --validate-links
      SLOW mode (used by the scheduled "Link Validation" workflow).
      Checks every homepage, updates deploy/link-status.json, and writes
      reports/latest.json, reports/latest.html and a dated archive copy.

An entry only gets the FIXME icon after it has failed FAIL_THRESHOLD
checks in a row, so a one-night outage or a flaky host doesn't flag a
healthy link.
"""
import argparse
import glob
import json
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

MAX_WORKERS = 30

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

# Seconds to wait on a slow host. NOTE: requests applies this to the
# connect and to each individual read, not to the whole download.
REQUEST_TIMEOUT = 10

# Retries only apply to connection setup (not to HTTP errors). Combined
# with REQUEST_TIMEOUT, one dead host can cost ~2x REQUEST_TIMEOUT.

# Where the persisted per-link failure counts live.
STATUS_FILE_DEFAULT = os.path.join(os.path.dirname(__file__), "link-status.json")

# An entry shows the FIXME icon once it has failed this many consecutive
# nightly checks.
FAIL_THRESHOLD = 2

# ---- human-readable descriptions for link-check failure reasons ----
HTTP_STATUS_DESCRIPTIONS = {
    400: "Bad Request - the server couldn't understand the request as sent.",
    401: "Unauthorized - the page requires login/authentication.",
    403: "Forbidden - server refused access (often bot-detection, not a dead link).",
    404: "Not Found - the page no longer exists at this URL.",
    410: "Gone - the page existed before but was intentionally removed.",
    429: "Too Many Requests - the server is rate-limiting our checker.",
    500: "Internal Server Error - something broke on their server.",
    502: "Bad Gateway - an upstream/proxy server got an invalid response.",
    503: "Service Unavailable - their server is overloaded or down for maintenance.",
    504: "Gateway Timeout - an upstream/proxy server took too long to respond.",
}

REASON_DESCRIPTIONS = {
    "timeout": "No response within the timeout window - slow or unresponsive host.",
    "ssl_error": ("The site's SSL/TLS certificate couldn't be verified "
                  "(expired, self-signed, or missing intermediate certificate)."),
    "non_http_skipped": "Not an http(s) link, so it wasn't checked.",
    "no_homepage_field": "Entry has no homepage URL to check.",
    "unknown": "Validation didn't run or produced no result.",
}


def describe_reason(reason):
    """
    Turn a raw reason string (e.g. "http_429", "timeout",
    "request_exception: ...") into a brief description for the report.
    Falls back to a generic message for anything not explicitly mapped,
    so an unrecognized reason never breaks report generation.
    """
    if reason.startswith("http_"):
        try:
            code = int(reason.split("_", 1)[1])
        except (IndexError, ValueError):
            return "HTTP error - unrecognized status code."
        return HTTP_STATUS_DESCRIPTIONS.get(
            code, "HTTP error {} - see status code for detail.".format(code)
        )
    if reason.startswith("request_exception:"):
        return "Network/connection problem (DNS failure, refused connection, etc.)."
    if reason.startswith("unexpected_exception:") or reason.startswith("internal_error:"):
        return "Unexpected error while checking this link - see full reason for detail."
    return REASON_DESCRIPTIONS.get(reason, "No description available for this reason.")


# How many past runs' reports to keep in reports/archive/.
KEEP_N_ARCHIVED_REPORTS = 3


# =====================================================================
# Persisted link status
# =====================================================================
# link-status.json maps "<category>/<file>" to
#   {"homepage": "<url when last checked>", "fail_streak": n, "reason": "..."}
# Only entries that are currently failing appear in it. Recording the
# homepage means that if someone fixes the link, the old failure record
# is ignored immediately instead of waiting for the next nightly run.

def _entry_key(category, data_obj):
    return "{}/{}".format(category, data_obj.get("_rawFileName", ""))


def load_status_cache(path):
    """Load the status cache; a missing or unreadable file means 'no history'."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.warning("Ignoring unreadable status file {}: {}".format(path, e))
        return {}


def save_status_cache(cache, path):
    with open(path, "w") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
        f.write("\n")


def _cached_streak(status_cache, key, homepage):
    """Previous consecutive-failure count, or 0 if none / homepage changed."""
    prev = (status_cache or {}).get(key)
    if not isinstance(prev, dict):
        return 0
    if prev.get("homepage") != homepage:
        return 0
    try:
        return int(prev.get("fail_streak", 0))
    except (TypeError, ValueError):
        return 0


def build_status_cache(categories):
    """Build the cache to persist: only entries that failed this run."""
    cache = {}
    for category, items in categories.items():
        for d in items:
            streak = d.get("_fail_streak", 0)
            if streak > 0:
                cache[_entry_key(category, d)] = {
                    "homepage": d.get("homepage", ""),
                    "fail_streak": streak,
                    "reason": d.get("_status_reason", ""),
                }
    return cache


def scan_core_data(core_dir, validate_link=False, reports_dir=None, status_cache=None,
                   deadline=None):
    """
    Scan and load data entries.

    Every entry gets a `_status` (True = show OK icon, False = FIXME).

    - validate_link=False: no network. `_status` comes from `status_cache`
      (the last nightly result); entries with no history show OK.
    - validate_link=True: every homepage is checked. A failure bumps the
      entry's consecutive-failure count; `_status` turns False once that
      reaches FAIL_THRESHOLD. A success resets the count.

    `deadline` - optional time.monotonic() value. Once it passes, links not
    yet started are skipped and keep their previous status, so the run
    ends on time and still saves everything it did check.

    `reports_dir` - if given (and validate_link is True), reports are
    written there.
    """
    status_cache = status_cache or {}
    categories = OrderedDict()  # {category: [yaml]}
    category_names = os.listdir(core_dir)

    # ---- Pass 1: load all YAML files from disk (fast, no network) ----
    all_items = []  # list of (category, data_obj)
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
        # Fast path: no network. Icons come from the last nightly check.
        for category, data_obj in all_items:
            key = _entry_key(category, data_obj)
            streak = _cached_streak(status_cache, key, data_obj.get("homepage"))
            data_obj["_status"] = streak < FAIL_THRESHOLD
            categories[category].append(data_obj)
        return categories

    # ---- Pass 2: validate all homepage links concurrently ----
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(_check_with_deadline, data_obj.get("homepage"), deadline): (category, data_obj)
            for category, data_obj in all_items
        }

        done = 0
        skipped = 0
        for future in as_completed(future_to_item):
            done += 1
            if done % 250 == 0:
                write_msg("--- progress: {}/{} links handled\n".format(done, len(all_items)))
            category, data_obj = future_to_item[future]
            try:
                result = future.result()
            except Exception as e:
                logging.warning("Unexpected error validating link for {}: {}".format(
                    data_obj.get("_rawFileName"), e))
                result = {"ok": False, "reason": "internal_error: {}".format(e)}

            key = _entry_key(category, data_obj)
            prev = _cached_streak(status_cache, key, data_obj.get("homepage"))

            if result["ok"] is None:
                # Skipped (deadline hit): carry the previous status forward
                # untouched, and don't report it as a failure.
                skipped += 1
                streak = prev
                result = {"ok": True,
                          "reason": (status_cache.get(key) or {}).get("reason", "not_checked")
                          if prev else "not_checked"}
                data_obj["_check_ok"] = True
            else:
                streak = 0 if result["ok"] else prev + 1
                data_obj["_check_ok"] = result["ok"]       # this run's raw result
            data_obj["_fail_streak"] = streak
            data_obj["_status"] = streak < FAIL_THRESHOLD  # what the icon shows
            data_obj["_status_reason"] = result["reason"]
            categories[category].append(data_obj)

    if skipped:
        write_msg("WARNING: deadline reached; {} link(s) were not checked this run "
                  "and keep their previous status.\n".format(skipped))

    # Concurrent validation scrambles order, so restore alphabetical order.
    for category in categories:
        categories[category].sort(key=lambda d: d.get("_rawFileName", ""))

    if reports_dir:
        write_link_check_reports(categories, reports_dir)

    return categories


def _check_with_deadline(link, deadline):
    """Run one check, or skip it ({"ok": None}) if the deadline has passed."""
    if deadline is not None and time.monotonic() > deadline:
        return {"ok": None, "reason": "not_checked"}
    return do_validate_link(link)


def write_msg(msg):
    sys.stdout.write(msg)
    sys.stdout.flush()


def do_validate_link(link):
    """
    Validate the accessibility of a homepage link.

    Returns {"ok": bool, "reason": str}, e.g. {"ok": False, "reason":
    "http_404"}. Only the status line and headers are read; the body is
    never downloaded (stream=True), so a huge file can't stall a check.
    """
    ok = False
    reason = "unknown"

    if link:
        if link.startswith("http://") or link.startswith("https://"):
            rsp = None
            try:
                rsp = session.get(
                    link,
                    timeout=REQUEST_TIMEOUT,
                    headers=REQUEST_HEADERS,
                    stream=True,
                )
                ok = not (400 <= rsp.status_code < 600)
                reason = "http_{}".format(rsp.status_code)
                time.sleep(0.2)  # Be nice to servers
            except requests.exceptions.Timeout:
                ok = False
                reason = "timeout"
            except requests.exceptions.SSLError:
                ok = False
                reason = "ssl_error"
            except requests.exceptions.RequestException as e:
                ok = False
                reason = "request_exception: {}".format(e)
            except Exception as e:
                ok = False
                reason = "unexpected_exception: {}".format(e)
            finally:
                if rsp is not None:
                    rsp.close()
        else:
            ok = True
            reason = "non_http_skipped"
    else:
        reason = "no_homepage_field"

    write_msg("Validating {} ... {} ({})\n".format(
        link, "OK" if ok else "FIXME", reason))

    return {"ok": ok, "reason": reason}


# =====================================================================
# Report writing
# =====================================================================

def _collect_failures(categories):
    """Entries whose check failed in this run, as a flat list of dicts."""
    failures = []
    for category, items in categories.items():
        for d in items:
            if not d.get("_check_ok", True):
                reason = d.get("_status_reason", "")
                failures.append({
                    "category": category,
                    "file": d.get("_rawFileName", ""),
                    "title": d.get("title", ""),
                    "homepage": d.get("homepage", ""),
                    "reason": reason,
                    "description": describe_reason(reason),
                    "fail_streak": d.get("_fail_streak", 1),
                    "flagged": not d.get("_status", True),
                })
    return failures


def _write_html_report(failures, path, generated_at):
    """Write the failures list as a small, self-contained HTML page."""
    def esc(value):
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    rows_html = "\n".join(
        "<tr>"
        "<td>{category}</td>"
        "<td>{file}</td>"
        "<td>{title}</td>"
        "<td><a href=\"{homepage}\">{homepage}</a></td>"
        "<td>{reason}</td>"
        "<td>{description}</td>"
        "<td>{streak}</td>"
        "<td>{flagged}</td>"
        "</tr>".format(
            category=esc(f["category"]),
            file=esc(f["file"]),
            title=esc(f["title"]),
            homepage=esc(f["homepage"]),
            reason=esc(f["reason"]),
            description=esc(f["description"]),
            streak=esc(f["fail_streak"]),
            flagged="FIXME shown" if f["flagged"] else "not yet",
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
      <tr><th>Category</th><th>File</th><th>Title</th><th>Homepage</th>
          <th>Reason</th><th>What it means</th><th>Consecutive failures</th>
          <th>README icon</th></tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
</body>
</html>
""".format(generated_at=esc(generated_at), count=len(failures), rows=rows_html)

    with open(path, "w") as f:
        f.write(html)


def _prune_old_archives(archive_dir, keep):
    """Delete all but the newest `keep` archived HTML reports."""
    files = sorted(glob.glob(os.path.join(archive_dir, "link-check-report_*.html")))
    for old in files[:-keep] if keep > 0 else files:
        try:
            os.remove(old)
        except OSError as e:
            logging.warning("Could not remove old report {}: {}".format(old, e))


def write_link_check_reports(categories, reports_dir):
    """Write latest.json, latest.html and a dated archive copy."""
    archive_dir = os.path.join(reports_dir, "archive")
    os.makedirs(archive_dir, exist_ok=True)

    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    stamp = now.strftime("%Y%m%d-%H%M%S")

    failures = _collect_failures(categories)

    with open(os.path.join(reports_dir, "latest.json"), "w") as f:
        json.dump({"generated_at": generated_at, "failures": failures}, f, indent=2)
        f.write("\n")

    _write_html_report(failures, os.path.join(reports_dir, "latest.html"), generated_at)
    _write_html_report(
        failures,
        os.path.join(archive_dir, "link-check-report_{}.html".format(stamp)),
        generated_at,
    )
    _prune_old_archives(archive_dir, KEEP_N_ARCHIVED_REPORTS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--validate-links", action="store_true",
                        help="Check every homepage (slow), update the status file "
                             "and write reports/. Default: off.")
    parser.add_argument("--status-file", default=STATUS_FILE_DEFAULT,
                        help="Path of the link status cache (default: %(default)s)")
    parser.add_argument("--max-minutes", type=float, default=None,
                        help="Stop starting new link checks after this many minutes; "
                             "unchecked links keep their previous status.")
    args = parser.parse_args()
    deadline = (time.monotonic() + args.max_minutes * 60) if args.max_minutes else None

    pdir = os.path.dirname(os.path.abspath(__file__))
    template_file = os.path.join(pdir, "index.mako")
    core_dir = os.path.join(pdir, "..", "core")
    reports_dir = os.path.join(pdir, "..", "reports") if args.validate_links else None

    status_cache = load_status_cache(args.status_file)

    categories = scan_core_data(
        core_dir,
        validate_link=args.validate_links,
        reports_dir=reports_dir,
        status_cache=status_cache,
        deadline=deadline,
    )

    if args.validate_links:
        save_status_cache(build_status_cache(categories), args.status_file)

    with open(template_file, 'r') as f:
        rendered = Template(f.read()).render(categories=categories)
    with open(os.path.join(pdir, "index.rst"), "w") as of:
        of.write(rendered)
        of.write("\n")
