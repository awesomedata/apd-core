#!/bin/bash
set -e # Exit with nonzero exit code if anything fails

THISPATH=`dirname $0`

pip install -r $THISPATH/requirements.txt

python $THISPATH/validate.py
