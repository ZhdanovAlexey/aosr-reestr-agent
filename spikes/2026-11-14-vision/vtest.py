import os, sys, json, base64, time, urllib.request, subprocess, concurrent.futures as cf
key = subprocess.run([os.path.expanduser("~/.local/bin/neuraldeep-hub-key")], capture_output=True, text=True).stdout.strip()
imgs = [base64.b64encode(open(p, "rb").read()).decode() for p in sys.argv[1:3]]
out = sys.argv[3]
prompt = """Перед тобой две страницы скана акта освидетельствования скрытых работ. Верни строго JSON без пояснений:
{"номер_акта": "", "дата_акта": "ДД.ММ.ГГГГ", "название_работ": "", "организация_выполнившая_работы": "",
 "работы": [{"код_по_ведомости": "", "наименование": "", "количество": "", "ед_изм": ""}],
 "дата_начала": "ДД.ММ.ГГГГ", "дата_окончания": "ДД.ММ.ГГГГ",
 "приложения": ["текст приложения с числом листов"]}
Переписывай цифры и номера в точности как в документе, ничего не додумывай."""
def run(model):
    body = {"model": model, "temperature": 0, "max_tokens": 3000, "messages": [{"role": "user", "content":
        [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b}} for b in imgs]}]}
    req = urllib.request.Request("https://api.neuraldeep.ru/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=240))
        txt = r["choices"][0]["message"].get("content") or ""
        res = {"ok": True, "sec": round(time.time() - t, 1), "usage": r.get("usage"), "text": txt}
    except Exception as e:
        detail = e.read().decode()[:500] if hasattr(e, "read") else ""
        res = {"ok": False, "sec": round(time.time() - t, 1), "err": str(e), "detail": detail}
    json.dump(res, open(f"{out}/{model}.json", "w"), ensure_ascii=False, indent=1)
    return model, res
models = sys.argv[4:]
with cf.ThreadPoolExecutor(len(models)) as ex:
    for m, r in ex.map(run, models):
        print("=====", m, r["ok"], r["sec"], "s", (r.get("usage") or {}).get("prompt_tokens"), (r.get("usage") or {}).get("completion_tokens"))
        print(r.get("text") or (r.get("err"), r.get("detail")))
