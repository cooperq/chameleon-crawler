#!/usr/bin/env python3

# chameleon-crawler
#
# Copyright 2015 ghostwords.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from contextlib import contextmanager
from multiprocessing import current_process
from pyvirtualdisplay import Display
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from time import sleep


class CrawlerProcess(object):
    def __init__(self, headless=True, **kwargs):
        self.headless = headless

        self.crx = kwargs['crx']
        self.log = kwargs['logger']
        self.url_queue = kwargs['url_queue']
        self.result_queue = kwargs['result_queue']

        self.name = current_process().name

        self.crawl()

        self.log("%s is all done!" % self.name)

    def crawl(self):
        with self.selenium():
            # open the extension's background page in window 0
            # Chrome extension APIs just aren't there sometimes ...
            while True:
                self.get(
                    "chrome-extension://%s/_generated_background_page.html" %
                    self.extension_id)

                if self.js("return chrome.hasOwnProperty('tabs')"):
                    break

            # get a URL from the job queue
            while True:
                if self.url_queue.empty():
                    sleep(0.01)
                    continue

                url = self.url_queue.get()

                if url is None:
                    break

                # open a new window
                self.js('window.open()')
                # switch to the new window
                self.driver.switch_to_window(self.driver.window_handles[-1])

                # load the URL in the new window
                self.get(url)

                # TODO detect errors ("unable to connect to the Internet",
                # "This webpage is not available", ...)

                # wait to allow dynamic scripts to load/execute
                # TODO smarter waiting
                sleep(2)

                self.collect_data()

                # close the window opened above
                self.driver.close()
                # switch to window 0
                self.driver.switch_to_window(self.driver.window_handles[0])

    @contextmanager
    def selenium(self):
        self.startup()

        self.extension_id = self.get_extension_id()

        try:
            yield
        finally:
            self.shutdown()

    def startup(self):
        if self.headless:
            self.display = Display(visible=0, size=(1440, 900))
            self.display.start()

        opts = webdriver.chrome.options.Options()
        opts.add_extension(self.crx)
        self.driver = webdriver.Chrome(chrome_options=opts)
        self.driver.implicitly_wait(5)

        # communicate chromedriver and Xvfb PIDs back to crawler.py
        display_pid = self.display.pid if self.headless else None
        # NOTE Firefox is different: self.driver.binary.process.pid
        driver_pid = self.driver.service.process.pid
        self.result_queue.put((driver_pid, display_pid))

    def shutdown(self):
        self.driver.quit()
        if self.headless:
            self.display.stop()

    def collect_data(self):
        self.log("%s collecting data ..." % self.name)

        cwh = self.driver.current_window_handle
        # switch to window 0 (our extension's background page)
        self.driver.switch_to_window(self.driver.window_handles[0])

        self.js("""chrome.tabs.query({}, function (tabs) {
            window.result = tabs.reduce(function (memo, tab) {
                var data = tabData.get(tab.id);
                if (data) {
                    memo[data.url] = data;
                }
                return memo;
            }, {});
        });""")

        self.wait_for_script(
            "return typeof result == 'object' && !!result")
        self.result_queue.put(self.js("return result"))

        # switch back to original window
        self.driver.switch_to_window(cwh)

    def get(self, url):
        self.log("%s fetching %s ..." % (self.name, url))
        self.driver.get(url)

    def get_extension_id(self):
        self.driver.get("chrome://extensions-frame/")
        return self.driver.find_element_by_class_name(
            'extension-list-item-wrapper').get_attribute('id')

    def js(self, script):
        return self.driver.execute_script(script)

    def wait_for_script(self, script, timeout=5):
        return WebDriverWait(self.driver, timeout, poll_frequency=0.5).until(
            lambda drv: drv.execute_script(script),
            ("Timeout waiting for script to eval to True:\n%s" % script)
        )
