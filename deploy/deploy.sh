#!/bin/bash
set -e # Exit with nonzero exit code if anything fails

THISPATH=`dirname $0`
TARGET_REPO="git@github.com:awesomedata/awesome-public-datasets.git"

# Save some useful information
REPO=`git config remote.origin.url`
SSH_REPO=${REPO/https:\/\/github.com\//git@github.com:}
SHA=`git rev-parse --verify HEAD`

# Run our compile script
function doCompile {
    pip install -r $THISPATH/requirements.txt
    python $THISPATH/render.py
}
#doCompile

# Clone the target repo into target_repo
git clone --depth=50 --branch=master $TARGET_REPO target_repo

# Set useful signature info.
cd target_repo
git config user.name "xiaming.chen"
git config user.email "chenxm35@gmail.com"

# Update generated data file
cp ../deploy/index.rst README.rst

# If there are no changes to the compiled out (e.g. this is a README update) then just bail.
if git diff --quiet; then
    echo "No changes to the output on this push; exiting."
    exit 0
fi

# Commit the "changes", i.e. the new version.
# The delta will show diffs between new and old versions.
git add README.rst
git commit -m "Update README sha: ${SHA}"

# Now that we're all set up, we can push.
git push origin master
