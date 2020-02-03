#!/usr/bin/env python3
import csv
import requests

from pathlib import Path
from ruamel import yaml
from concurrent.futures import ProcessPoolExecutor


def read_core_files():
    core_path = Path('../core')

    file_metas = []
    for item in core_path.glob('**/*'):
        if item.is_dir() or item.name.startswith('.'):
            continue

        category, file_name = item.parts[-2:]

        file = core_path / category / file_name
        with file.open() as file:
            data_info = yaml.load(file.read(), Loader=yaml.Loader)

        file_metas.append({
            'category': category,
            'file_name': file_name,
            'url': data_info['homepage'],
        })

    return file_metas


def check_url(category, file_name, url):

    try:
        response = requests.head(url, allow_redirects=False, timeout=5)
        if response.status_code in [301, 302]:
            return category, file_name, url, f'Redirects to {response.headers["Location"]}'
    except Exception as e:
        return category, file_name, url, repr(e)


def check_urls(file_list):

    with ProcessPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(check_url, **file) for file in file_list]
        responses = [future.result() for future in futures]

    return [r for r in responses if r is not None]


def main():
    files = read_core_files()

    issues = check_urls(files)

    with open('check_urls.csv', 'w') as f:
        writer = csv.writer(f)
        writer.writerow(['Category', 'File Name', 'Url', 'Issue'])
        [writer.writerow(r) for r in issues]


if __name__ == '__main__':
    main()
