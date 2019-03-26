# CONTRIBUTING

## On AwesomeData community

The AwesomeData community consists primarily, although not solely, of its online presence in mailing lists and activities such as blog postings and comments, the GitHub repository, and so on. The vision of the AwesomeData community is contributing a pure list of `high quality` datasets for open communities such as academia, research, education etc.

The following policy is a guideline to propose new data items and maintain existing items with outdated information:

1. A dataset is considered as `high quality` when one or more of the following criteria are met:
    * Uncommon to obtain in the open community legally;
    * Contributing valuable knowledge for a specific domain;
    * Able to be downloaded directly from the linked site, i.e., not barred by login or purchasing;
    * No advertisement! No Spam! No reputation promotion!

2. A new pull request will be merged into the core repository after passing automatic validation and maintainer's review.

3. An existing dataset item with outdated information (e.g., unavailable site) will be removed after a while without new update.

## How to contribute a new data entry

It is simple to contribute to APD:

1. Fork `apd-core` repository into your own namespace such as `yourname/apd-core`.

2. Clone your project locally:
```bash
git clone https://github.com/yourname/apd-core.git
cd apd-core
```

3. Create a new data entry from template `PULL_REQUEST_TEMPLATE.yml`. 

For example, we want create `NEW_DATASET.yml` under category folder of `Government`:
```bash
cp PULL_REQUEST_TEMPLATE.yml ./core/Government/NEW_DATASET.yml
```
Then edit data fields as you want:
```bash
vim ./core/Government/NEW_DATASET.yml 
```
For data validation, it requires three essential data fields: `title`, `homepage` and `category`, while the `category` should be the same with the folder name, i.e., "Government" in the example.

In a nutshell, you should get a basic entry like
```yaml
---
title: New Dataset Name
homepage: https://example.com
category: Government
```

4. Run local test to validate your modification:
```bash
# With python
sudo pip install -r tests/requirements.txt
./tests/testing.sh
```

5. Commit local modifications to your repository:
```bash
git add ./core/Government/NEW_DATASET.yml
git commit -m "Add NEW_DATASET under government"  # Any message as you want
git push origin master
```

6. Create a new Pull Request to the trunk repository on Github page, usually `https://github.com/yourname/apd-core/pulls`