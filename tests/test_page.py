"""The page in a real browser, on the fictional examples, without the model.

    pip install playwright && playwright install chromium
    pytest tests/test_page.py

    SOTTOVOCE_BROWSER=chrome pytest tests/test_page.py    # use the Chrome you have

Skipped when Playwright is not installed. Recording itself cannot run here (it
needs a real tab to share), so its panel is checked, not the capture.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from conftest import NORTHPINE, ROOT, SUPPLIER

playwright = pytest.importorskip("playwright.sync_api")
CHANNEL = os.environ.get("SOTTOVOCE_BROWSER") or None


def launch(pw):
    return pw.chromium.launch(channel=CHANNEL)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def site(data):
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "server.py"), "--no-model", "--port", str(port),
         "--data", str(data / "transcripts"), "--glossary", str(data / "glossary.txt")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(100):
        try:
            if urllib.request.urlopen(url + "health", timeout=1).read() == b"ok":
                break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def page(site):
    with playwright.sync_playwright() as pw:
        browser = launch(pw)
        p = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto(site)
        yield p
        assert errors == [], errors
        browser.close()


def open_call(p, name):
    p.locator(".item", has_text=name.split("_", 1)[1]).click()
    p.wait_for_selector(".reader")


def test_the_choices_before_transcribing_are_explained_and_remembered(page):
    tiles = page.locator(".options .option")
    assert tiles.count() == 3
    assert "Voice 1" in page.locator("#voices-toggle").inner_text()
    page.locator("#precise-toggle").click()
    assert "on" in page.locator("#precise-toggle").get_attribute("class")
    page.reload()
    assert page.locator("#precise-toggle input").is_checked()


def test_the_voices_panel_comes_first_on_a_call(page):
    open_call(page, NORTHPINE)
    assert page.locator(".side .panel h2").first.inner_text() == "Voices"


def test_the_page_opens_on_a_new_transcription_not_on_a_call(page):
    assert page.locator("h1").inner_text() == "New transcription"
    assert page.locator("#drop").is_visible()
    assert page.locator("#record-panel").is_visible()
    page.wait_for_function("document.querySelector('[data-need=model]').textContent === 'Transcription off'")
    names = page.locator(".item .name").all_inner_texts()
    assert names[0].startswith("Supplier check-in")              # newest first
    assert len(names) == 4


def test_a_call_reads_three_ways_and_the_strip_plays_from_a_point(page):
    open_call(page, NORTHPINE)
    tabs = page.locator(".tabs button")
    assert tabs.nth(0).get_attribute("aria-selected") == "true"
    assert page.locator(".reader .summary").is_visible()
    tabs.nth(2).click()
    assert page.locator(".reader p[data-i]").count() == 55
    assert page.locator(".reader .w").count() > 500                   # clickable words
    strip = page.locator("#strip")
    box = strip.bounding_box()
    tabs.nth(0).click()
    strip.click(position={"x": box["width"] * 0.6, "y": 10})
    assert tabs.nth(1).get_attribute("aria-selected") == "true"
    assert page.evaluate("document.querySelector('.reader').scrollTop") > 50


def test_getting_back_to_the_start(page):
    page.wait_for_function("document.querySelector('[data-need=model]').textContent === 'Transcription off'")
    open_call(page, NORTHPINE)
    page.locator(".crumbs button").click()
    assert page.locator("h1").inner_text() == "New transcription"
    # The rebuilt home still knows the model is off (it once said "Choose files").
    assert page.locator("[data-need=model]").inner_text() == "Transcription off"
    open_call(page, NORTHPINE)
    page.keyboard.press("Escape")
    assert page.locator("h1").inner_text() == "New transcription"
    open_call(page, NORTHPINE)
    page.locator("#mark").click()
    assert page.locator("h1").inner_text() == "New transcription"


def test_two_tracks_say_who_spoke(page):
    open_call(page, SUPPLIER)
    page.locator(".tabs button").nth(2).click()
    who = page.locator(".reader .who").all_inner_texts()
    assert who[:2] == ["You", "Them"]
    assert "two tracks" in page.locator(".finding").inner_text()


def test_search_and_jump(page):
    page.fill("#search", "photos")
    page.wait_for_selector(".hit")
    page.locator(".hit").first.click()
    page.wait_for_selector(".reader p[data-t]")
    assert page.locator(".tabs button").nth(1).get_attribute("aria-selected") == "true"


def test_download_menu_offers_every_format(page):
    open_call(page, SUPPLIER)
    page.locator(".menu summary").click()
    links = page.locator(".menu-list a").evaluate_all("a => a.map(x => x.getAttribute('href'))")
    assert [h.rsplit(".", 1)[1] for h in links] == ["md", "txt", "srt", "vtt", "json"]


def test_glossary_view(page):
    page.locator("#v-glossary").click()
    page.wait_for_selector("text=Name glossary")
    assert page.locator("tbody tr").count() == 3


def test_phone_width(site):
    with playwright.sync_playwright() as pw:
        browser = launch(pw)
        p = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        p.goto(site)
        p.wait_for_selector("#drop")
        assert p.evaluate("document.documentElement.scrollWidth") <= 390
        assert p.locator("#sidebar").bounding_box()["x"] < 0             # folded away
        p.locator("#open-list").click()
        p.wait_for_function("document.getElementById('sidebar').classList.contains('open')")
        browser.close()



def test_voices_have_their_own_colour_and_take_a_name(page):
    open_call(page, NORTHPINE)
    assert "3 voices told apart" in page.locator(".finding").inner_text()
    page.locator(".tabs button").nth(2).click()
    assert page.locator(".reader .who").all_inner_texts()[:3] == ["Voice 1", "Voice 2", "Voice 1"]
    assert page.locator(".reader .who.v2").count() == 22
    page.fill("input[name='Voice 2']", "Daniel")
    with page.expect_response(lambda r: "/api/history/" in r.url):
        page.locator("text=Save names").click()
    page.wait_for_selector(".reader")
    page.locator(".tabs button").nth(2).click()
    assert page.locator(".reader .who").all_inner_texts()[:2] == ["Voice 1", "Daniel"]
    assert page.locator("input[name='Voice 2']").input_value() == "Daniel"
