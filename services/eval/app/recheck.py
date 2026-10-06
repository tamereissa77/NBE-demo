"""Re-apply automatic checks to stored answers after a check in prompts.yaml is corrected
(no regeneration):  python -m app.recheck"""
from app import db
from app.gate import auto_check, load


def main() -> None:
    items = {i["id"]: i for i in load()["items"]}
    changed = 0
    with db.connect() as conn:
        for row in conn.execute("SELECT id, item_id, alias, text, tool_calls, auto_pass FROM eval.outputs").fetchall():
            ok, detail = auto_check(items[row["item_id"]], row["text"] or "", row["tool_calls"] or [])
            if ok != row["auto_pass"]:
                changed += 1
                print(f"  {row['item_id']} {row['alias']}: {row['auto_pass']} -> {ok} ({detail})")
            conn.execute("UPDATE eval.outputs SET auto_pass=%s, auto_detail=%s WHERE id=%s", (ok, detail, row["id"]))
    print(f"rechecked; {changed} changed")


if __name__ == "__main__":
    main()
