#!/usr/bin/env python
import os
from collections import OrderedDict

import yaml
from mako.template import Template


def scan_core_data(core_dir):
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
            categories[category].append(data_obj)

    return categories


if __name__ == '__main__':
    pdir = os.path.dirname(__file__)
    template_file = os.path.join(pdir, 'index.mako')
    core_dir = os.path.join(pdir, '..', 'core')

    categories = scan_core_data(core_dir)

    rendered = Template(open(template_file).read()).render(categories=categories)
    with open(os.path.join(pdir, 'index.rst'), 'w') as of:
        of.write(rendered)
        of.write('\n')
