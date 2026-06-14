import sqlite3
import os

candidates = [
    "data/aquant.db",
    "data/test_data/test.db",
    "data/test_data/aquant.db",
    "data/research.db",
]
for path in candidates:
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"\n=== {path} ({size} bytes) ===")
        try:
            c = sqlite3.connect(path)
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )]
            print(f"  tables: {tables}")
            for t in tables:
                try:
                    cnt = c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
                    print(f"    {t}: {cnt} rows")
                except Exception as e:
                    print(f"    {t}: ERR {e}")
            c.close()
        except Exception as e:
            print(f"  ERR: {e}")
    else:
        print(f"\n=== {path}: NOT EXIST ===")
