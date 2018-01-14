#!/usr/bin/env python
from mako.template import Template
import os

pdir = os.path.dirname(__file__)
template_file = os.path.join(pdir, 'index.mako')

rendered = Template(open(template_file).read()).render(data="world")
with open(os.path.join(pdir, 'index.rst'), 'w') as of:
	of.write(rendered)
	of.write('\n')
