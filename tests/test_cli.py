import json
import subprocess
import sys


def run(home, *args):
    p = subprocess.run([sys.executable, "-m", "aosr", "--home", str(home), *map(str, args)], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


def test_cli_json_contract(tmp_path, small_template, acts_xlsx):
    home = tmp_path / "home"
    assert run(home, "init", "--template", small_template) == (0, {"ok": True})
    code, out = run(home, "ingest", acts_xlsx)
    assert code == 0 and out["ok"] and out["total"] == 12
    code, out = run(home, "find", "--from", "2024-08-01", "--to", "2024-08-31")
    assert code == 0 and out["count"] > 0
    code, out = run(home, "set", "ВО/11-15/БО", "place", "колодцы 11-15")
    assert code == 0 and out["new"] == "колодцы 11-15"
    code, out = run(home, "show", "НЕТ/0")
    assert code == 1 and out["ok"] is False and out["error"]["code"] == "act_not_found" and out["error"]["message"]
    code, out = run(tmp_path / "empty", "summary")
    assert code == 1 and out["error"]["code"] == "no_registry"
    code, out = run(home, "undo")
    assert code == 0 and out["undone"].startswith("исправлено поле")
