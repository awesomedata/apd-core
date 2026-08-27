#!/usr/bin/env python
import logging
import os
import sys
import time
from collections import OrderedDict

import requests
import yaml
from mako.template import Template
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed

session = requests.Session()
session.mount("http://", HTTPAdapter(max_retries=1))
session.mount("https://", HTTPAdapter(max_retries=1))

# Number of concurrent link checks in flight at once.
# 10-20 is a reasonable range: high enough to get a big speedup,
# low enough to avoid hammering any single slow host or getting
# rate-limited/blocked by sites that don't like bursts of requests.
MAX_WORKERS = 15

def scan_core_data(core_dir, validate_link=False):
    """Scan and load data entries"""
    categories = OrderedDict()  # {catetory: [yaml]}
    category_names = os.listdir(core_dir)

    # ---- Pass 1: load all YAML files from disk (fast, no network) ----
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
        # No network work needed — just group by category, in original order.
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
                data_obj["_status"] = future.result()
            except Exception as e:
                logging.warning("Unexpected error validating link for {}: {}".format(
                    data_obj.get("_rawFileName"), e))
                data_obj["_status"] = False
            categories[category].append(data_obj)

    # Concurrent validation scrambles order, so restore alphabetical order
    # to match what the .mako template expects.
    for category in categories:
        categories[category].sort(key=lambda d: d.get("_rawFileName", ""))

    return categories

def write_msg(msg):
    sys.stdout.write(msg)
    sys.stdout.flush()


def do_validate_link(link):
    """Validate the accessibility of web like"""
    _status = False
    if link:
        if link.startswith("http") or link.startswith("https"):
            try:
                # TODO: validate redirection
                rsp = session.get(link, timeout=4)
                _status = False if 400 <= rsp.status_code < 600 else True
                time.sleep(0.2)  # Be nice to servers
            except Exception as e:
                logging.warning(
                    "Failed to validate link {}, caused by {}".format(link, e)
                )
        else:
            _status = True  # Omit non-http site currently
    write_msg("Validating {} ... {}\n".format(link, "OK" if _status else "FIXME"))
    return _status


if __name__ == "__main__":
    pdir = os.path.dirname(__file__)
    template_file = os.path.join(pdir, "index.mako")
    core_dir = os.path.join(pdir, "..", "core")

    categories = scan_core_data(core_dir, validate_link=True)

    with open(template_file, 'r') as f:
        rendered = Template(f.read()).render(categories=categories)
    with open(os.path.join(pdir, "index.rst"), "w") as of:
        of.write(rendered)
        of.write("\n")
