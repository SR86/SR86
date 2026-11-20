"""One bounded campus login; credentials stay in Windows Credential Manager."""
import argparse
import json
import time
from network_check import is_online

LOGIN_URL='http://172.16.253.3/a79.htm'
SERVICE='CampusNetwork'


def authenticate(visible=False, check=is_online):
    if check():return 'already_online'
    import keyring
    username=keyring.get_password(SERVICE,'username')
    password=keyring.get_password(SERVICE,'password')
    if not username or not password:return 'credentials_missing'
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=not visible,args=['--no-proxy-server'])
        try:
            page=browser.new_page()
            page.goto(LOGIN_URL,wait_until='domcontentloaded',timeout=20000)
            account=page.locator('input[type="text"][name="DDDDD"]')
            pwd=page.locator('input[type="password"][name="upass"]')
            agreement=page.locator('input[type="checkbox"][name="C1"]')
            submit=page.locator('input[type="submit"][name="0MKKey"]')
            if any(x.count()!=1 for x in (account,pwd,agreement,submit)):
                return 'already_online' if check() else 'form_unrecognized'
            # Submit through the existing form and its own Javascript handlers.
            account.fill(username);pwd.fill(password);agreement.check()
            if check():return 'already_online'
            submit.click(timeout=15000)
            for _ in range(3):
                if check():return 'online'
                time.sleep(2)
            # Inspect only for a known rejection; never log the page or its URL.
            body=page.locator('body').inner_text(timeout=3000)[:20000]
            if any(x in body for x in ('密码错误','账号或密码错误','账户被锁定','账号被锁定')):
                return 'credentials_rejected'
            return 'verification_failed'
        finally:browser.close()


EXIT={'online':0,'already_online':0,'credentials_missing':2,
      'form_unrecognized':3,'credentials_rejected':4,'verification_failed':1}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--visible',action='store_true')
    try:
        result=authenticate(visible=parser.parse_args().visible)
        print(json.dumps({'status':result}));raise SystemExit(EXIT[result])
    except Exception as exc:
        print(json.dumps({'status':'error','error_type':type(exc).__name__}));raise SystemExit(1)
