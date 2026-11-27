"""Exercise the merged file tool using synthetic ownership and a class deck in the real page."""
import argparse
import json
from pathlib import Path

from _test_account import TEST_SID
from identity_sync_check import IdentityService
from sync_browser_fixture import browser_fixture, click, screenshot, wait


class FileService(IdentityService):
    tables = IdentityService.tables + ["ppt_decks", "mine", "state"]

    def __call__(self, request):
        if request["table"] in ("mine", "state"):
            assert request["token"] == "fixture-a"
            session = {"id": "test-session"}
            if request["table"] == "mine":
                return 200, {"ok": True, "session": session}, {}
            assert request["query"]["sessionId"] == session["id"]
            assert request["query"]["ppt"] == "1"
            return 200, {"ok": True, "session": session, "pptConversion": True, "files": [
                {"id": "test-file", "name": "个人练习.pptx", "size": 1024, "downloadUrl": "/drop/file/test-file"}
            ], "events": []}, {}
        if request["table"] == "ppt_decks":
            assert request["token"] == "fixture-a"
            assert request["method"] == "GET"
            return 200, [{"id": "qa-deck", "title": "测试课件", "source_name": "qa.pptx", "status": "ready"}], {}
        return super().__call__(request)


def main(output):
    service = FileService()
    service.rows[TEST_SID] = {"id": TEST_SID, "blob": json.dumps({
        "v": 6, "at": {"homeTools": 123}, "homeTools": ["ppt", "draw", "file"]})}
    with browser_fixture(service) as open_page:
        page = open_page(seed="localStorage.zq_all_order_v1=JSON.stringify(['ppt','draw','file']);")
        wait(page, "!!document.querySelector('#tabsBar [data-tab=file]')")
        for width, height in [(390, 844), (430, 932), (1100, 780)]:
            page.set_device(width, height, 1, width < 600)
            click(page, "#tabsBar [data-tab=all]")
            assert page.evaluate("document.querySelectorAll('[data-card=file]').length") == 1
            assert page.evaluate("document.querySelector('[data-card]').dataset.card") == "file"
            assert not page.evaluate("document.querySelector('[data-card=ppt],[data-tab=ppt]')!==null")
            click(page, "[data-card=file] button[data-open=file]")
            wait(page, "!!document.querySelector('#s-file.on')")
            wait(page, "document.querySelector('#fileList').textContent.includes('个人练习.pptx')")
            assert not page.evaluate("document.querySelector('#fileList').textContent.includes('测试课件')")
            screenshot(page, output, f"personal-{width}")
            click(page, "#fileClassDecks")
            wait(page, "document.querySelector('#s-ppt.on #pptList').textContent.includes('测试课件')")
            assert page.evaluate("document.querySelector('#tabsBar [data-tab=file]').classList.contains('on')")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert not page.evaluate("document.querySelector('#pptList').textContent.includes('个人练习.pptx')")
            screenshot(page, output, f"decks-{width}")
            click(page, "#classDecksPrivateFiles")
            assert page.evaluate("document.querySelector('#s-file.on')!==null")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.evaluate("location.hash='ppt'")
        wait(page, "!!document.querySelector('#s-ppt.on')")
        page.evaluate("location.hash='file'")
        wait(page, "!!document.querySelector('#s-file.on')")
        assert not page.evaluate("window.jsErrors"), page.evaluate("window.jsErrors")
        assert not page.evaluate("document.querySelector('.bottom-nav')!==null")
        page.close()
    print("PASS catalog, saved order, account shortcuts, both file sections, #ppt/#file and class deck; 3 viewports, overflow=0, navCount=0, ERR=(none)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path)
    main(parser.parse_args().artifacts)
