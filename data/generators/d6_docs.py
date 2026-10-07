"""D6 local documentation corpus: real docstrings of commonly used pandas and numpy APIs, extracted from
the installed libraries (offline, version-accurate). Code answers are grounded in these to cut
hallucinated APIs (PLAN.md §4 D6)."""
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("/repo/data/generated/d6")
TARGETS = {
    "pandas": [pd.read_csv, pd.read_excel, pd.to_datetime, pd.merge, pd.concat, pd.pivot_table, pd.DataFrame.groupby,
               pd.DataFrame.agg, pd.DataFrame.sort_values, pd.DataFrame.head, pd.DataFrame.resample, pd.DataFrame.fillna,
               pd.DataFrame.dropna, pd.DataFrame.drop_duplicates, pd.DataFrame.apply, pd.DataFrame.astype, pd.DataFrame.query,
               pd.DataFrame.loc.__class__, pd.DataFrame.to_csv, pd.DataFrame.to_excel, pd.DataFrame.rolling, pd.DataFrame.value_counts,
               pd.DataFrame.describe, pd.DataFrame.set_index, pd.DataFrame.reset_index, pd.DataFrame.rename, pd.DataFrame.isin,
               pd.Series.str.__class__, pd.Series.dt.__class__, pd.Series.map, pd.Series.cumsum, pd.DataFrame.nlargest, pd.cut, pd.qcut],
    "numpy": [np.where, np.mean, np.median, np.percentile, np.round, np.isnan, np.nan_to_num, np.cumsum, np.unique, np.clip,
              np.linspace, np.arange, np.std, np.corrcoef],
}


def build() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(OUT / "docs.jsonl", "w", encoding="utf-8") as f:
        for lib, objs in TARGETS.items():
            version = pd.__version__ if lib == "pandas" else np.__version__
            for obj in objs:
                name = f"{lib}.{getattr(obj, '__qualname__', getattr(obj, '__name__', str(obj)))}"
                doc = inspect.getdoc(obj) or ""
                try:
                    sig = str(inspect.signature(obj))
                except (TypeError, ValueError):
                    sig = ""
                text = f"{name}{sig}\n(library version {version})\n\n{doc[:6000]}"
                f.write(json.dumps({"name": name, "library": lib, "version": version, "text": text}, ensure_ascii=False) + "\n")
                n += 1
    return n


if __name__ == "__main__":
    print(f"D6: {build()} API docs (pandas {pd.__version__}, numpy {np.__version__})")
