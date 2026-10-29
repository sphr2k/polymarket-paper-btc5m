from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
import sqlite3,json,os
DB=os.environ.get("PAPER_DB", "/data/paper.sqlite3")
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  path=urlsplit(self.path).path
  if path=="/":
   data=open("/app/index.html","rb").read();typ="text/html; charset=utf-8"
  elif path=="/api":
   try:
    with sqlite3.connect("file:"+DB+"?mode=ro",uri=True) as c:
     c.row_factory=sqlite3.Row
     q=lambda sql:[dict(r) for r in c.execute(sql)]
     data=json.dumps({"stats":q("SELECT (SELECT count(*) FROM markets) markets,(SELECT count(*) FROM snapshots) samples,(SELECT count(*) FROM settlements) resolved,(SELECT count(*) FROM trials) trials,(SELECT max(ts) FROM snapshots) latest")[0],"series":q("SELECT ts,up_best_ask up,down_best_ask down FROM snapshots WHERE slug=(SELECT slug FROM markets ORDER BY start_ts DESC LIMIT 1) ORDER BY ts DESC LIMIT 250")[::-1],"strategies":q("SELECT strategy,count(*) n,count(settled_pnl) settled,round(sum(settled_pnl),3) pnl FROM trials GROUP BY strategy"),"trials":q("SELECT ts,slug,strategy,side,ask,gross_usd,settled_pnl FROM trials ORDER BY ts DESC LIMIT 25")},separators=(",",":")).encode();typ="application/json"
   except (sqlite3.Error,OSError):
    self.send_response(503);self.end_headers();return
  else:self.send_response(404);self.end_headers();return
  self.send_response(200);self.send_header("Content-Type",typ);self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff");self.send_header("Content-Security-Policy","default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'");self.end_headers();self.wfile.write(data)
 def do_POST(self):self.send_response(405);self.end_headers()
ThreadingHTTPServer(("0.0.0.0",8080),Handler).serve_forever()
