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

logger = logging.getLogger(__name__)

session = requests.Session()
session.mount('http://', HTTPAdapter(max_retries=3))
session.mount('https://', HTTPAdapter(max_retries=3))


def scan_core_data(core_dir, validate_link=False):
    """Scan and load data entries
    """
    categories = OrderedDict()  # {catetory: [yaml]}
    category_names = os.listdir(core_dir)

    for category in sorted(category_names):
        print('Scanned category: ', category)
        if category not in categories:
            categories[category] = list()

        for data_item in sorted(os.listdir(os.path.join(core_dir, category))):
            data_file = os.path.join(core_dir, category, data_item)

            try:
                data_obj = yaml.load(open(data_file))
            except Exception as e:
                raise RuntimeError('Failed to read YAML data: {}'.format(e))

            if validate_link:
                homepage = data_obj.get('homepage')
                data_obj['_status'] = do_validate_link(homepage)

            categories[category].append(data_obj)

    return categories


def write_msg(msg):
    sys.stdout.write(msg)
    sys.stdout.flush()


def do_validate_link(link):
    """Validate the accessibility of web like"""
    _status = False
    if link:
        if link.startswith('http') or link.startswith('https'):
            try:
                rsp = session.get(link)
                _status = False if 400 <= rsp.status_code < 600 else True
                time.sleep(0.1)  # Be nice to servers
            except Exception as e:
                logger.warning('Failed to validate link {}, caused by {}'.format(link, e))
        else:
            _status = True  # Omit non-http site currently
    write_msg('Validating {}...{}\n'.format(link, 'OK' if _status else 'FIXME'))
    return _status


if __name__ == '__main__':
    pdir = os.path.dirname(__file__)
    template_file = os.path.join(pdir, 'index.mako')
    core_dir = os.path.join(pdir, '..', 'core')

    categories = scan_core_data(core_dir, validate_link=True)

    rendered = Template(open(template_file).read()).render(categories=categories)
    with open(os.path.join(pdir, 'index.rst'), 'w') as of:
        of.write(rendered)
        of.write('\n')
