#!/bin/bash
set -e # Exit with nonzero exit code if anything fails

# Update generated data file
cd awesome-public-datasets
if [ ! -e ../deploy/index.rst ]; then
    echo "ERROR:Can not find rendered meta file. Please run render.py first ahead"
    exit 1
fi
cp ../deploy/index.rst README.rst

# If there are no changes to the compiled out (e.g. this is a README update) then just bail.
if git diff --quiet; then
    echo "INFO:No changes to the output on this push; exiting."
    exit 0
fi

git config user.name "xiaming.chen"
git config user.email "chenxm35@gmail.com"

# Commit the "changes", i.e. the new version.
# The delta will show diffs between new and old versions.
git add README.rst
git commit -m "Update README sha: $(git rev-parse --verify HEAD)"

# Now that we're all set up, we can push.
git push origin master
