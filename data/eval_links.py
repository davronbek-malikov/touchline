"""Report SB <-> TM linking accuracy on the hand-labelled sample.

Label data/labels/link_sample.csv by filling `is_correct` (1/0) for every row:
  - linked rows: 1 if tm_name is the same person as sb_name, else 0
  - unmatched rows: 1 if the player truly has no Transfermarkt entry, else 0
    (put the right id in correct_tm_player_id when you know it)

Usage: python -m data.eval_links
"""
import pandas as pd

from data.config import ROOT

PATH = ROOT / "data" / "labels" / "link_sample.csv"


def report(df: pd.DataFrame) -> dict:
    labelled = df[df["is_correct"].notna()]
    linked = labelled[labelled["tm_player_id"].notna()]
    unmatched = labelled[labelled["tm_player_id"].isna()]
    out = {
        "labelled": len(labelled),
        "accuracy": labelled["is_correct"].mean(),
        "link_precision": linked["is_correct"].mean() if len(linked) else None,
        "unmatched_correct": unmatched["is_correct"].mean() if len(unmatched) else None,
        "by_method": labelled.groupby("method")["is_correct"].agg(["mean", "count"]).to_dict("index"),
    }
    return out


if __name__ == "__main__":
    df = pd.read_csv(PATH)
    r = report(df)
    if not r["labelled"]:
        print(f"No labels yet: fill is_correct in {PATH}")
    else:
        print(f"labelled rows:      {r['labelled']}")
        print(f"overall accuracy:   {r['accuracy']:.1%}")
        if r["link_precision"] is not None:
            print(f"link precision:     {r['link_precision']:.1%}")
        if r["unmatched_correct"] is not None:
            print(f"correctly unlinked: {r['unmatched_correct']:.1%}")
        for m, v in r["by_method"].items():
            print(f"  {m:28s} {v['mean']:.1%}  (n={v['count']})")
