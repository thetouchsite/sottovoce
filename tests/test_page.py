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
        p = browser.new_page(locale="en-US", viewport={"width": 1440, "height": 900})
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
    page.wait_for_function("document.getElementById('engine-text').textContent.includes('browsing only')")
    # Adding a file needs no model: it only waits to be transcribed.
    assert page.locator("#drop .primary").is_enabled()
    page.wait_for_selector(".item .name")                          # the list arrives after the page
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
    page.wait_for_function("document.getElementById('engine-text').textContent.includes('browsing only')")
    open_call(page, NORTHPINE)
    page.locator(".crumbs button").click()
    assert page.locator("h1").inner_text() == "New transcription"
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
    page.locator(".menu:not(.more) summary").click()
    links = page.locator(".menu-list a").evaluate_all("a => a.map(x => x.getAttribute('href'))")
    assert [h.rsplit(".", 1)[1] for h in links] == ["notes", "md", "txt", "srt", "vtt", "json"]


def test_glossary_view(page):
    page.locator("#v-glossary").click()
    page.wait_for_selector("text=Name glossary")
    assert page.locator("tbody tr").count() == 3


def test_phone_width(site):
    with playwright.sync_playwright() as pw:
        browser = launch(pw)
        p = browser.new_page(locale="en-US", viewport={"width": 390, "height": 844}, is_mobile=True)
        p.goto(site)
        p.wait_for_selector("#drop")
        assert p.evaluate("document.documentElement.scrollWidth") <= 390
        assert p.locator("#sidebar").bounding_box()["x"] < 0             # folded away
        p.locator("#open-list").click()
        p.wait_for_function("document.getElementById('sidebar').classList.contains('open')")
        p.mouse.click(375, 700)                                        # a tap beside it
        p.wait_for_function("!document.getElementById('sidebar').classList.contains('open')")
        browser.close()


def test_on_a_phone_the_recording_comes_first_and_the_choices_fold(site):
    with playwright.sync_playwright() as pw:
        browser = launch(pw)
        ctx = browser.new_context(locale="en-US", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        p = ctx.new_page()
        p.goto(site)
        p.wait_for_selector("#drop")
        assert p.locator(".drop b:visible").all_inner_texts() == ["Send a recording"]
        drop_y = p.locator("#drop").bounding_box()["y"]
        assert drop_y < p.locator(".options-panel").bounding_box()["y"]
        assert not p.locator(".options").is_visible()
        assert "Detect language" in p.locator(".options-summary").inner_text()
        p.locator(".options-panel>header").tap()
        assert p.locator(".options").is_visible()
        assert not p.locator("#shutdown").is_visible()           # not stoppable from a phone
        browser.close()


def test_on_a_phone_a_line_is_corrected_with_taps(site, data):
    with playwright.sync_playwright() as pw:
        browser = launch(pw)
        ctx = browser.new_context(locale="en-US", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        p = ctx.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto(site)
        p.locator("#open-list").tap()
        p.locator(".item", has_text="Supplier check-in").tap()
        p.wait_for_selector(".reader")
        assert p.locator(".jumps button").all_inner_texts()[:3] == ["Transcript", "Email", "Voices"]
        p.locator(".tabs button").nth(2).tap()
        assert p.locator(".tabs button").nth(2).inner_text() == "Lines"
        p.get_by_role("button", name="Correct").tap()
        p.locator(".reader p[data-i='0'] span.text").tap()
        p.keyboard.press("Control+End")              # the end of the text, not of the wrapped row
        p.keyboard.type(" Bye.")
        with p.expect_response(lambda r: "/api/correct/" in r.url):
            p.locator(".edit-actions .primary").tap()
        p.wait_for_function("document.querySelector(\".reader p[data-i='0'] span.text\").textContent.endsWith('Bye.')")
        # Cancel really cancels: the button must not let the blur save first.
        p.locator(".reader p[data-i='1'] span.text").tap()
        p.keyboard.type("XXX")
        p.locator(".edit-actions .text-button").tap()
        assert "XXX" not in p.locator(".reader p[data-i='1']").inner_text()
        txt = (data / "transcripts" / SUPPLIER / "Supplier check-in, Brenna Print.txt").read_text(encoding="utf-8")
        assert "Bye." in txt.splitlines()[0] and "XXX" not in txt
        assert errors == []
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


def test_a_file_added_waits_in_the_list_and_can_be_renamed_and_deleted(page, tmp_path):
    f = tmp_path / "Team call.wav"
    f.write_bytes(b"RIFF....WAVEfmt ")
    page.wait_for_function("document.getElementById('engine-text').textContent.includes('browsing only')")
    page.locator("#file").set_input_files(str(f))
    page.wait_for_selector(".go .primary")
    assert page.locator("h1").inner_text() == "Team call.wav"
    assert "not transcribed yet" in page.locator(".finding").inner_text()
    # No model here: the button says why it can't start, instead of failing.
    assert page.locator(".go .primary").inner_text() == "Transcription off"
    item = page.locator(".item", has_text="Team call")
    assert item.locator(".state.waiting").inner_text() == "Not transcribed"
    page.locator(".menu.more summary").click()
    page.locator(".menu-list button", has_text="Rename").click()
    page.locator(".rename input").fill("Team call, Monday")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('h1') && document.querySelector('h1').textContent === 'Team call, Monday'")
    assert page.locator(".item", has_text="Team call, Monday").count() == 1
    page.once("dialog", lambda d: d.accept())
    page.locator(".menu.more summary").click()
    page.locator(".menu-list button", has_text="Delete").click()
    page.wait_for_function("document.querySelector('h1').textContent === 'New transcription'")
    assert page.locator(".item", has_text="Team call").count() == 0


def test_a_transcribed_call_can_be_renamed(page):
    open_call(page, SUPPLIER)
    page.locator(".menu.more summary").click()
    page.locator(".menu-list button", has_text="Rename").click()
    assert page.locator(".rename input").input_value() == "Supplier check-in, Brenna Print"
    page.keyboard.press("Escape")                  # closes the field, stays on the call
    assert page.locator("h1").inner_text() == "Supplier check-in, Brenna Print.webm"


def test_the_page_in_italian_leaves_the_calls_as_they_are(site):
    with playwright.sync_playwright() as pw:
        browser = launch(pw)
        ctx = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 900})
        ctx.add_init_script("if (!localStorage.getItem('sottovoce-ui')) localStorage.setItem('sottovoce-ui', 'it')")
        p = ctx.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto(site)
        assert p.locator("h1").inner_text() == "Nuova trascrizione"
        assert p.locator("html").get_attribute("lang") == "it"
        p.locator(".item", has_text="Northpine").click()
        p.wait_for_selector(".reader")
        assert "3 voci separate" in p.locator(".finding").inner_text()
        p.locator(".tabs button").nth(2).click()
        assert p.locator(".tabs button").nth(2).inner_text() == "Riga per riga"
        assert p.locator(".reader .who").first.inner_text() == "Voce 1"
        # The transcript is data: never translated, even where a line is one word.
        assert p.locator(".reader p[data-i='0'] span.text").inner_text().startswith("Okay, I think")
        assert p.locator("h1").inner_text() == "Northpine launch sync.m4a"
        p.locator("#ui-lang").click()                     # back to English
        p.wait_for_selector("h1")
        assert p.locator("html").get_attribute("lang") == "en"
        assert errors == []
        browser.close()


def test_a_call_offers_notes_and_a_follow_up_email(page):
    open_call(page, NORTHPINE)
    page.locator(".menu:not(.more) summary").click()
    assert page.locator(".menu-list a").first.get_attribute("href").endswith("/download.notes")
    page.keyboard.press("Escape")
    assert page.locator("#p-followup h2").inner_text() == "Follow-up email"



def test_an_italian_system_gets_the_page_in_italian_until_a_choice_is_made(site):
    with playwright.sync_playwright() as pw:
        browser = launch(pw)
        p = browser.new_page(locale="it-IT", viewport={"width": 1440, "height": 900})
        p.goto(site)
        assert p.locator("h1").inner_text() == "Nuova trascrizione"
        with p.expect_navigation():
            p.locator("#ui-lang").click()                               # the choice wins, and stays
        assert p.locator("h1").inner_text() == "New transcription"
        browser.close()


def test_in_the_window_recording_opens_the_browser_and_the_power_button_quits(site):
    with playwright.sync_playwright() as pw:
        browser = launch(pw)
        p = browser.new_page(locale="en-US", viewport={"width": 1440, "height": 900})
        p.goto(site + "?window")
        assert p.locator("#record-panel button.primary").inner_text() == "Record in the browser"
        assert p.locator("#shutdown").get_attribute("title") == "Quit Sottovoce"
        with p.expect_popup() as tab:
            p.locator("#record-panel button.primary").click()
        assert tab.value.url == site
        browser.close()


def test_a_recording_stops_when_another_call_opens(page, data):
    # The old player used to keep sounding, detached, with no button to stop it.
    import math
    import struct
    import wave
    with wave.open(str(data / "transcripts" / NORTHPINE / "Northpine launch sync.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(8000 * 60)))
    page.evaluate("""() => { window.players = [];
        const play = HTMLMediaElement.prototype.play;
        HTMLMediaElement.prototype.play = function(){ window.players.push(this); return play.call(this); }; }""")
    open_call(page, NORTHPINE)
    page.locator(".player button").click()
    page.wait_for_function("window.players.length === 1")
    open_call(page, SUPPLIER)
    page.wait_for_function("window.players.every(a => a.paused && !a.ended)", timeout=3000)
