import json
rec = json.load(open("0006.json", encoding="utf-8"))
print("path:", rec.get("path"))
print("req_text:", rec.get("req_text"))
b = rec.get("req_body_b64") or ""
if b:
    import base64
    txt = base64.b64decode(b).decode("utf-8", "replace")
    print("req_body keys/len:", [(k, len(str(v))) for k, v in (json.loads(txt).items() if txt.strip().startswith("{") else [])])
    print("req_body prefix:", txt[:120])
