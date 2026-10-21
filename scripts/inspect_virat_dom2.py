import json
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.connect_over_cdp('http://127.0.0.1:9350');page=next(t for c in b.contexts for t in c.pages if t.url.startswith('https://chatgpt.com/c/6ad8efc9'))
 print(json.dumps(page.evaluate("""()=>{const marker='OTO-virat-kohli-2026-10-21-P12-identity-v6';const match=[...document.querySelectorAll('div,p,span')].find(x=>x.textContent.includes(marker)&&![...x.children].some(c=>c.textContent.includes(marker)));let a=match;const chain=[];for(let i=0;a&&i<6;i++,a=a.parentElement)chain.push({tag:a.tagName,attrs:[...a.attributes].map(x=>[x.name,x.value])});return {chain,images:[...document.images].slice(-3).map(x=>({alt:x.alt,parent:x.parentElement.outerHTML.slice(0,450)}))}}""")))
