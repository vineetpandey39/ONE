import json
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.connect_over_cdp('http://127.0.0.1:9350')
 page=next(t for c in b.contexts for t in c.pages if t.url.startswith('https://chatgpt.com/c/6ad8efc9'))
 print(json.dumps(page.evaluate("""()=>({roles:[...document.querySelectorAll('[data-message-author-role]')].map(x=>({role:x.getAttribute('data-message-author-role'),text:(x.innerText||'').slice(-100)})).slice(-4),articles:[...document.querySelectorAll('article')].slice(-4).map(x=>({attrs:[...x.attributes].map(a=>[a.name,a.value]),text:(x.innerText||'').slice(-150)}))})""")))
