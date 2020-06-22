#!/usr/bin/env python
from collections import OrderedDict

import os
import yaml


def scan_core_data(core_dir):
    """Scan and load data entries
    """
    categories = OrderedDict()  # {catetory: [yaml]}
    category_names = os.listdir(core_dir)

    for category in sorted(category_names):
        print('Scanned category: %s' % category)
        if category not in categories:
            categories[category] = list()

        for data_item in sorted(os.listdir(os.path.join(core_dir, category))):
            data_file = os.path.join(core_dir, category, data_item)
            categories[category].append(data_file)

    return categories


def validate_classification(category_map):
    for category, entries in category_map.items():
        for entry in entries:
            try:
                data_obj = yaml.load(open(entry), Loader=yaml.Loader)
            except Exception as e:
                raise RuntimeError('Failed to read YAML data: {}'.format(e))

            assert data_obj.get('title', None) is not None
            assert data_obj.get('homepage', None) is not None
            assert data_obj.get('category', None) is not None

            assert data_obj.get('category') == category


if __name__ == '__main__':
    pdir = os.path.dirname(__file__)
    core_dir = os.path.join(pdir, '..', 'core')

    categories = scan_core_data(core_dir)
    validate_classification(categories)
