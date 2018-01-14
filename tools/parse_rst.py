#!/usr/bin/env python3
import re
import yaml
import sys
import copy
import os

from ruamel import yaml
from ruamel.yaml import YAML

# Load template
template = yaml.load(open('dataset.yml.template', 'rb').read())

category = None
categories = {}

item_regex = r'`([^`<>]+)<([^<>]*)>`_'


def parse_categoried_data(input_file):
	for line in open(input_file):
		line = line.strip('\r\n ')
		if len(line) == 0:
			continue

		if line.endswith('<<<<<'):
			category = line[:-5].replace(' ', '').replace('/', '+')
			continue

		if category not in categories:
			categories[category] = list()

		searched = re.search(item_regex, line)
		if searched is None:
			print('ERROR: ' + line)
		else:
			name = searched.group(1).split('-', 1)[0]
			name = name.strip(' ').replace(' ', '-') \
				.replace("'", "") \
				.replace('(', '') \
				.replace(')', '') \
				.replace(',', '') \
				.replace('/', '')
			description = searched.group(1).strip('"\r\n ')
			link = searched.group(2)

			t = copy.deepcopy(template)
			t['category'] = category
			t['name'] = name
			t['title'] = description
			t['homepage'] = link

			categories[category].append(t)

parse_categoried_data('awesome-public-datasets.rst')
parse_categoried_data('Government.rst')

y = YAML()
y.default_flow_style = None
y.explicit_start = True
y.indent(sequence=4, offset=2)

outdir = '../core'
for c in categories:
	if not os.path.exists(outdir):
		os.mkdir(outdir)

	cdir = os.path.join(outdir, c)
	if not os.path.exists(cdir):
		os.mkdir(cdir)

	for item in categories[c]:
		name = item.pop('name')
		ofile = os.path.join(cdir, '%s.yml' % name)
		with open(ofile, 'w') as of:
			y.dump(item, of)
