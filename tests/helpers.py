"""Shared setup for the test scripts in this directory. Not a test file
itself — nothing in here is collected/run on its own."""
import os
import pathlib

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX_URL = 'file://' + str(ROOT / 'index.html')
CHROME_BIN = os.environ.get('CHROME_BIN', '/usr/bin/chromium')
CHROMEDRIVER_BIN = os.environ.get('CHROMEDRIVER_BIN', '/usr/bin/chromedriver')


def make_driver(window_size=(1500, 1000)):
    opts = Options()
    opts.binary_location = CHROME_BIN
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument(f'--window-size={window_size[0]},{window_size[1]}')
    return webdriver.Chrome(service=Service(executable_path=CHROMEDRIVER_BIN), options=opts)


class Results:
    """Tiny pass/fail collector shared by every test script here, so
    they all print and exit the same way."""
    def __init__(self):
        self.items = []  # (passed: bool, label: str, detail: str|None)

    def check(self, passed, label, detail=None):
        self.items.append((bool(passed), label, detail))
        return passed

    def summarize(self):
        failed = [r for r in self.items if not r[0]]
        print(f"{len(self.items) - len(failed)}/{len(self.items)} passed")
        if failed:
            print("\nFAILURES:")
            for _, label, detail in failed:
                print(f" - {label}" + (f": {detail}" if detail else ""))
        return 1 if failed else 0
