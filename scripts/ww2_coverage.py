"""How much of the world has province-level divisions? Share of land and population by tier,
per snapshot and per political unit. Writes ww2/coverage.csv and ww2/coverage_by_unit.csv
(ww2/coverage_1900_1934.csv and coverage_by_unit_1900_1934.csv with WW2_SET=early)."""
import pandas as pd

from ww2_common import SET, SNAPSHOTS, WW2_OUT, WW2_WORK

TIER_ZH = {3: "省级", 4: "大区级", 5: "整个国家/殖民地", 6: "岛屿属地"}


def main():
    hist = pd.read_csv(WW2_WORK / "prov_units.csv", low_memory=False).set_index("unit_id")
    rows, by_unit = [], []
    for snap, _, _ in SNAPSHOTS:
        d = pd.read_csv(WW2_WORK / f"prov_snapshot_{snap}.csv", low_memory=False)
        d["tier"] = d.admin_id.map(hist.tier)
        t = d.groupby("tier").agg(area=("area_km2", "sum"), pop=("population_est", "sum"), units=("admin_id", "nunique"))
        t["area_share"] = (t.area / t.area.sum()).round(4)
        t["pop_share"] = (t["pop"] / t["pop"].sum()).round(4)
        for tier, r in t.iterrows():
            rows.append(dict(snapshot=snap, tier=int(tier), tier_zh=TIER_ZH[int(tier)], admin_units=int(r.units),
                             area_km2=round(r.area), population_est=int(r["pop"]), area_share=r.area_share,
                             pop_share=r.pop_share))
        u = d.groupby(["unit_name_zh", "unit_name_en"]).apply(
            lambda x: pd.Series({"population_est": int(x.population_est.sum()),
                                 "provinces": int(x[x.tier == 3].admin_id.nunique()),
                                 "finest_tier": int(x.tier.min()),
                                 "pop_share_province": round(x[x.tier == 3].population_est.sum() / max(x.population_est.sum(), 1), 3),
                                 "pop_share_region_or_finer": round(x[x.tier <= 4].population_est.sum() / max(x.population_est.sum(), 1), 3)}),
            include_groups=False).reset_index()
        u.insert(0, "snapshot", snap)
        by_unit.append(u.sort_values("population_est", ascending=False))
    out = pd.DataFrame(rows)
    sfx = "" if SET == "ww2" else "_1900_1934"
    out.to_csv(WW2_OUT / f"coverage{sfx}.csv", index=False)
    pd.concat(by_unit).to_csv(WW2_OUT / f"coverage_by_unit{sfx}.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
