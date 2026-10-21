import json,urllib.request,websocket
pages=json.load(urllib.request.urlopen('http://127.0.0.1:9350/json'))
p=next(p for p in pages if p.get('url','').startswith('https://chatgpt.com/c/6ad8efc9'))
w=websocket.create_connection(p['webSocketDebuggerUrl'],suppress_origin=True)
expr="JSON.stringify({roles:[...document.querySelectorAll('[data-message-author-role]')].map(x=>({role:x.getAttribute('data-message-author-role'),text:(x.innerText||'').slice(-100)})).slice(-4),articles:[...document.querySelectorAll('article')].slice(-4).map(x=>({attrs:[...x.attributes].map(a=>[a.name,a.value]),text:(x.innerText||'').slice(-150)}))})"
w.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':expr,'returnByValue':True}}))
while True:
 r=json.loads(w.recv())
 if r.get('id')==1:print(json.dumps(r.get('result',{})));break
w.close()
