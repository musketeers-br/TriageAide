"""Capture targeted screenshots from the Gradio UI for the article.

Prerequisites:
  pip install playwright && python -m playwright install chromium
"""

import time
import os
from playwright.sync_api import sync_playwright

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
GRADIO_URL = "http://localhost:7860"


def _send_message(page, message: str):
    """Fill the chat textarea and click Send."""
    textarea = page.locator('textarea[placeholder*="Type your message"]')
    textarea.fill(message)

    send_btn = page.locator('button:has-text("Send")')
    send_btn.click()


def _wait_for_response(page, timeout=120):
    """Wait for the Gradio agent to finish generating a response."""
    time.sleep(3)
    for i in range(timeout):
        generating = page.locator(".generating")
        if generating.count() == 0:
            return True
        time.sleep(1)
    return False


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
        )
        page = context.new_page()

        # 1. Blank UI
        print("Capturing blank UI...")
        page.goto(GRADIO_URL, wait_until="load")
        page.wait_for_selector(".gradio-container", timeout=30000)
        time.sleep(5)
        path = os.path.join(OUT_DIR, "screenshot_blank_ui.png")
        page.screenshot(path=path, full_page=False)
        print(f"  {path}")

        # 2. After Joao Santos first message (Steps 1+2 visible in trace)
        print("Sending Joao Santos message 1...")
        _send_message(page, "Hi, I'm Joao Santos, I've been having trouble breathing at night and my legs are swollen")
        _wait_for_response(page, timeout=90)
        time.sleep(2)
        path = os.path.join(OUT_DIR, "screenshot_joao_step1_2.png")
        page.screenshot(path=path, full_page=True)
        print(f"  {path}")

        # 3. After bruising/bleeding message (red flags appear in trace)
        print("Sending Joao Santos message 2 (bruising/bleeding)...")
        _send_message(page, "Yes, I've been noticing some bruising easily and my gums bleed when I brush my teeth")
        _wait_for_response(page, timeout=90)
        time.sleep(2)
        path = os.path.join(OUT_DIR, "screenshot_joao_red_flags.png")
        page.screenshot(path=path, full_page=True)
        print(f"  {path}")

        # 4. After dizziness/fatigue (full triage with clinical assessment)
        print("Sending Joao Santos message 3 (dizziness/fatigue)...")
        _send_message(page, "I've also been feeling dizzy when I stand up, and I'm more tired than usual")
        _wait_for_response(page, timeout=180)
        time.sleep(2)
        path = os.path.join(OUT_DIR, "screenshot_joao_full_triage.png")
        page.screenshot(path=path, full_page=True)
        print(f"  {path}")

        browser.close()

    print("\nDone! Screenshots saved to:", OUT_DIR)


if __name__ == "__main__":
    main()
