"""Theory-vs-practice analysis and report generation.

Each section tests one worst-case bound against the measured behaviour and
asks which *structural* quantity actually drives the cost:

  A. Tree-decomposition DP     O(2^tw * n)          -> slope of log2(states) in tw
  B. Branch & bound            O*(1.4656^k)         -> k vs "above-LP" gap k - LP*
  C. ILP branch & cut          exponential          -> integrality gap OPT - LP*
  D. Greedy                    H(Delta)             -> clustering / degree structure
  E. Matching 2-approx         2                    -> density
  F. LP rounding / NT-flow     2                    -> half-integral fraction
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.tree import DecisionTreeRegressor, export_text, plot_tree

from .algorithms import APPROX, PORTFOLIO
from .algorithms.common import harmonic
from . import selection as S

FAM_ORDER = ["er", "ba", "ws", "plc", "rgg", "ktree", "bipartite", "sbm", "trap"]
CMAP = dict(zip(FAM_ORDER, plt.get_cmap("tab10").colors))


def _runs(datadir) -> pd.DataFrame:
    datadir = Path(datadir)
    inst = pd.read_csv(datadir / "instances.csv")
    runs = pd.read_csv(datadir / "runs.csv").merge(inst, on="instance")
    runs["ratio"] = runs["size"] / runs["opt"]
    runs["ok"] = runs["status"].eq("ok")
    return runs


def _spearman(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 5:
        return float("nan"), float("nan")
    r, p = stats.spearmanr(x[m], y[m])
    return float(r), float(p)


def _scatter(ax, df, x, y, logy=False, s=12):
    for fam in FAM_ORDER:
        d = df[df["family"] == fam]
        if len(d):
            ax.scatter(d[x], d[y], s=s, alpha=0.7, color=CMAP[fam], label=fam, edgecolors="none")
    if logy:
        ax.set_yscale("log")
    ax.set_xlabel(x)
    ax.set_ylabel(y)


def analyse(datadir="data", outdir="reports") -> dict:
    datadir, outdir = Path(datadir), Path(outdir)
    fig_dir = outdir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    R = _runs(datadir)
    known = R["opt_source"].isin(["portfolio", "ilp_ref"])
    lp = (R[R.algorithm == "lp_round"].set_index("instance")["x_lp_value"])
    R["lp_value"] = R["instance"].map(lp)
    R["int_gap"] = R["opt"] - R["lp_value"]           # integrality gap (absolute)
    out: dict = {}

    # ---------------- A. tree decomposition DP ----------------
    D = R[(R.algorithm == "td_dp")].copy()
    D["width"] = D["x_width"]
    Dok = D[D.ok & (D.x_states > 0)]
    sl = stats.linregress(Dok["width"], np.log2(Dok["x_states"] / Dok["n"]))
    slt = stats.linregress(Dok["width"], np.log2(Dok["time"]))
    big = Dok[Dok["width"] >= 8]
    slt_big = stats.linregress(big["width"], np.log2(big["time"])) if len(big) > 5 else None
    rho_w, _ = _spearman(Dok["time"].values, Dok["width"].values)
    rho_n, _ = _spearman(Dok["time"].values, Dok["n"].values)
    rho_m, _ = _spearman(Dok["time"].values, Dok["m"].values)
    out["td_dp"] = {
        "solved_frac": float(D.ok.mean()),
        "states_slope_per_width": sl.slope, "states_slope_r2": sl.rvalue ** 2,
        "time_slope_per_width": slt.slope, "time_slope_r2": slt.rvalue ** 2,
        "time_slope_per_width_w>=8": None if slt_big is None else slt_big.slope,
        "max_width_solved": int(Dok["width"].max()),
        "max_tw_ub_solved": int(D[D.ok]["tw_ub"].max()),
        "min_tw_ub_failed": int(D[~D.ok]["tw_ub"].min()) if (~D.ok).any() else None,
        "median_tw_ub_failed": float(D[~D.ok]["tw_ub"].median()) if (~D.ok).any() else None,
        "spearman_time_vs_width": rho_w, "spearman_time_vs_n": rho_n,
        "spearman_time_vs_m": rho_m,
        "tw_feature_vs_width_spearman": _spearman(D["tw_ub"].values, D["width"].values)[0],
        # Cheeger link: small spectral gap <=> sparse cuts <=> small separators / treewidth
        "spearman_lap_gap_vs_tw_ratio": _spearman(D["lap_gap"].values, D["tw_ratio"].values)[0],
        "spearman_lap_gap_vs_dp_solved": _spearman(D["lap_gap"].values, D["ok"].astype(float).values)[0],
        "dp_solved_frac_lap_gap_le_0.154": float(D[D.lap_gap <= 0.154].ok.mean()),
        "dp_solved_frac_lap_gap_gt_0.154": float(D[D.lap_gap > 0.154].ok.mean()),
    }
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    _scatter(ax[0], Dok, "width", "time", logy=True)
    ww = np.linspace(Dok.width.min(), Dok.width.max(), 50)
    ax[0].plot(ww, 2 ** (slt.intercept + slt.slope * ww), "k--",
               label=f"fit: 2^({slt.slope:.2f} w)")
    ax[0].set_title("Tree-decomposition DP: time vs width")
    ax[0].legend(fontsize=7, ncol=2)
    bins = np.arange(0, D["tw_ub"].max() + 4, 3)
    D["twbin"] = pd.cut(D["tw_ub"], bins)
    fr = D.groupby("twbin", observed=True)["ok"].mean()
    ax[1].bar([str(b) for b in fr.index], fr.values, color="tab:blue")
    ax[1].set_title("DP solved within budget vs treewidth feature (tw_ub)")
    ax[1].tick_params(axis="x", rotation=60)
    fig.tight_layout(); fig.savefig(fig_dir / "A_td_dp_width.png", dpi=130); plt.close(fig)

    # ---------------- B. branch and bound ----------------
    B = R[(R.algorithm == "bnb") & R.ok & known].copy()
    B["k"] = B["opt"]
    B["above_lp"] = B["opt"] - B["lp_value"]
    B["log_nodes"] = np.log2(B["ops"])
    fitk = stats.linregress(B["k"], B["log_nodes"])
    hard = B[B["ops"] > 50]
    fit_gap = stats.linregress(hard["above_lp"], hard["log_nodes"]) if len(hard) > 5 else None
    out["bnb"] = {
        "solved_frac": float(R[R.algorithm == "bnb"].ok.mean()),
        "theory_base": 1.4656,
        "empirical_base_per_k": float(2 ** fitk.slope), "r2_k": fitk.rvalue ** 2,
        "spearman_nodes_vs_k": _spearman(B["ops"].values, B["k"].values)[0],
        "spearman_nodes_vs_n": _spearman(B["ops"].values, B["n"].values)[0],
        "spearman_nodes_vs_above_lp": _spearman(B["ops"].values, B["above_lp"].values)[0],
        "spearman_nodes_vs_density": _spearman(B["ops"].values, B["density"].values)[0],
        "empirical_base_per_above_lp_unit": None if fit_gap is None else float(2 ** fit_gap.slope),
        "frac_solved_at_root": float((B["ops"] <= 1).mean()),
    }
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    _scatter(ax[0], B, "k", "ops", logy=True)
    kk = np.linspace(B.k.min(), B.k.max(), 50)
    ax[0].plot(kk, 1.4656 ** kk, "k:", label="worst case 1.4656^k")
    ax[0].set_ylim(0.5, B["ops"].max() * 5)
    ax[0].set_title("B&B search nodes vs cover size k"); ax[0].legend(fontsize=7, ncol=2)
    _scatter(ax[1], B, "above_lp", "ops", logy=True)
    ax[1].set_title("B&B search nodes vs above-LP gap (k - LP*)")
    fig.tight_layout(); fig.savefig(fig_dir / "B_bnb_nodes.png", dpi=130); plt.close(fig)

    # ---------------- C. ILP ----------------
    Iall = R[(R.algorithm == "ilp") & known].copy()
    I = Iall[Iall.ok]
    out["ilp"] = {
        "solved_frac": float(R[R.algorithm == "ilp"].ok.mean()),
        "spearman_time_vs_int_gap": _spearman(I["time"].values, I["int_gap"].values)[0],
        "spearman_time_vs_n": _spearman(I["time"].values, I["n"].values)[0],
        "spearman_time_vs_density": _spearman(I["time"].values, I["density"].values)[0],
        "frac_root_solved": float((I["ops"] <= 1).mean()),
        "mean_int_gap_solved": float(I["int_gap"].mean()),
        "mean_int_gap_timeout": float(Iall[~Iall.ok]["int_gap"].mean()) if (~Iall.ok).any() else None,
    }
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    _scatter(ax[0], I, "int_gap", "time", logy=True)
    ax[0].set_title("ILP time vs integrality gap OPT - LP*")
    Iall = Iall.copy()
    Iall["gapbin"] = pd.cut(Iall["int_gap"], [-0.01, 0.5, 2, 5, 10, 20, 1e9])
    fr = Iall.groupby("gapbin", observed=True)["ok"].mean()
    ax[1].bar([str(b) for b in fr.index], fr.values, color="tab:orange")
    ax[1].set_title("ILP solved within budget vs integrality gap")
    fig.tight_layout(); fig.savefig(fig_dir / "C_ilp_gap.png", dpi=130); plt.close(fig)

    # ---------------- D. greedy ----------------
    G = R[(R.algorithm == "greedy") & known].copy()
    deg_max = G["max_deg_ratio"] * G["avg_deg"]
    G["H_bound"] = [harmonic(int(round(d))) if d >= 1 else 1.0 for d in deg_max]
    G["subopt"] = (G["ratio"] > 1).astype(int)
    nontrap = G[G.family != "trap"]
    feats = ["clustering", "transitivity", "deg_cv", "density", "avg_deg", "tw_ratio",
             "assortativity", "is_bipartite", "lap_gap", "frac_leaves", "degeneracy_ratio"]
    corr = {f: _spearman(nontrap["ratio"].values, nontrap[f].values)[0] for f in feats}
    stump = DecisionTreeRegressor(max_depth=2, min_samples_leaf=15).fit(nontrap[feats], nontrap["ratio"])
    cl_bins = pd.cut(nontrap["clustering"], [-0.01, 0.05, 0.2, 0.4, 0.6, 1.0])
    by_cl = nontrap.groupby(cl_bins, observed=True)["ratio"].agg(["mean", "max", "count"])
    by_cl["p_subopt"] = nontrap.groupby(cl_bins, observed=True)["subopt"].mean()
    as_bins = pd.cut(nontrap["assortativity"], [-1.01, -0.3, -0.15, 0.0, 0.15, 1.0])
    by_as = nontrap.groupby(as_bins, observed=True)["ratio"].agg(["mean", "max", "count"])
    by_as["p_subopt"] = nontrap.groupby(as_bins, observed=True)["subopt"].mean()
    cv_bins = pd.cut(nontrap["deg_cv"], [-0.01, 0.2, 0.4, 0.7, 1.0, 10])
    by_cv = nontrap.groupby(cv_bins, observed=True)["ratio"].agg(["mean", "max", "count"])
    by_cv["p_subopt"] = nontrap.groupby(cv_bins, observed=True)["subopt"].mean()
    T = G[G.family == "trap"].copy()
    T["k"] = T["params"].map(lambda s: json.loads(s)["k"])
    T["noise"] = T["params"].map(lambda s: json.loads(s)["noise"])
    trap_tab = T.groupby(["k", "noise"])["ratio"].mean().unstack()
    out["greedy"] = {
        "mean_ratio": float(G["ratio"].mean()), "max_ratio": float(G["ratio"].max()),
        "frac_optimal": float((G["ratio"] == 1).mean()),
        "bound_ever_violated": bool((G["ratio"] > G["H_bound"] + 1e-9).any()),
        "max_ratio_over_bound": float((G["ratio"] / G["H_bound"]).max()),
        "spearman_ratio_vs_feature_nontrap": corr,
        "stump_rules": export_text(stump, feature_names=feats, decimals=3),
        "by_clustering": by_cl.round(4).reset_index().astype(str).to_dict("records"),
        "by_assortativity": by_as.round(4).reset_index().astype(str).to_dict("records"),
        "by_deg_cv": by_cv.round(4).reset_index().astype(str).to_dict("records"),
        "trap_ratio_by_k_noise": trap_tab.round(3).to_dict(),
        "trap_H_k_minus_1": {int(k): round(harmonic(k) - 1, 3) for k in sorted(T["k"].unique())},
    }
    fig, ax = plt.subplots(1, 3, figsize=(15, 4))
    _scatter(ax[0], G, "H_bound", "ratio")
    hb = np.linspace(1, G["H_bound"].max(), 20)
    ax[0].plot(hb, hb, "k:", label="worst case H(Δ)")
    ax[0].set_title("Greedy ratio vs its worst-case bound"); ax[0].legend(fontsize=7, ncol=2)
    _scatter(ax[1], nontrap, "clustering", "ratio")
    ax[1].set_title("Greedy ratio vs clustering (non-trap)")
    for nz, d in T.groupby("noise"):
        g = d.groupby("k")["ratio"].mean()
        ax[2].plot(g.index, g.values, "o-", label=f"noise={nz}")
    ks = np.array(sorted(T["k"].unique()))
    ax[2].plot(ks, [harmonic(k) - 1 for k in ks], "k:", label="H(k) - 1 (exact trap)")
    ax[2].set_xlabel("k"); ax[2].set_ylabel("ratio"); ax[2].legend(fontsize=7)
    ax[2].set_title("Greedy on Johnson trap: tight bound & robustness")
    fig.tight_layout(); fig.savefig(fig_dir / "D_greedy.png", dpi=130); plt.close(fig)

    # ---------------- E/F. 2-approximations ----------------
    A = R[R.algorithm.isin(["matching", "lp_round", "nt_flow"]) & known].copy()
    M = A[A.algorithm == "matching"]
    L = A[A.algorithm == "lp_round"]
    N = A[A.algorithm == "nt_flow"]
    out["matching"] = {
        "mean_ratio": float(M["ratio"].mean()), "max_ratio": float(M["ratio"].max()),
        "spearman_ratio_vs_density": _spearman(M["ratio"].values, M["density"].values)[0],
        "spearman_ratio_vs_avg_deg": _spearman(M["ratio"].values, M["avg_deg"].values)[0],
        "mean_ratio_density_gt_0.3": float(M[M.density > 0.3]["ratio"].mean()),
        "mean_ratio_density_lt_0.05": float(M[M.density < 0.05]["ratio"].mean()),
    }
    out["lp_round"] = {
        "mean_ratio": float(L["ratio"].mean()), "max_ratio": float(L["ratio"].max()),
        "spearman_ratio_vs_half_frac": _spearman(L["ratio"].values, L["lp_half_frac"].values)[0],
        "frac_certified": float(L["proved"].astype(bool).mean()),
        "mean_ratio_bipartite": float(L[L.is_bipartite == 1]["ratio"].mean()),
    }
    out["nt_flow"] = {
        "mean_ratio": float(N["ratio"].mean()), "max_ratio": float(N["ratio"].max()),
        "frac_certified": float(N["proved"].astype(bool).mean()),
        "mean_ratio_nonbipartite": float(N[N.is_bipartite == 0]["ratio"].mean()),
        "frac_better_than_greedy": float(
            (N.set_index("instance")["size"] < G.set_index("instance")["size"]).mean()),
        "frac_worse_than_greedy": float(
            (N.set_index("instance")["size"] > G.set_index("instance")["size"]).mean()),
    }
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    _scatter(ax[0], M, "density", "ratio")
    ax[0].axhline(2, color="k", ls=":"); ax[0].set_xscale("log")
    ax[0].set_title("Matching 2-approx ratio vs density")
    _scatter(ax[1], L, "lp_half_frac", "ratio")
    ax[1].axhline(2, color="k", ls=":")
    ax[1].set_title("LP rounding ratio vs half-integral fraction")
    ax[1].legend(fontsize=7, ncol=2)
    fig.tight_layout(); fig.savefig(fig_dir / "E_two_approx.png", dpi=130); plt.close(fig)

    # ---------------- summary tables ----------------
    rows = []
    for a, (_, para, unit, bound) in PORTFOLIO.items():
        d = R[(R.algorithm == a)]
        dk = d[known.loc[d.index] & d.ok]
        rows.append({"algorithm": a, "paradigm": para, "unit": unit, "worst-case": bound,
                     "solved": f"{d.ok.mean():.1%}",
                     "median time [ms]": round(1000 * d[d.ok]["time"].median(), 2),
                     "mean ratio": round(dk["ratio"].mean(), 4),
                     "max ratio": round(dk["ratio"].max(), 4),
                     "% optimal": f"{(dk['ratio'] == 1).mean():.1%}"})
    out["portfolio_table"] = pd.DataFrame(rows)
    out["family_time"] = R[R.ok].pivot_table(index="family", columns="algorithm",
                                             values="time", aggfunc="median").reindex(FAM_ORDER)
    out["family_solved"] = R.pivot_table(index="family", columns="algorithm", values="ok",
                                         aggfunc="mean").reindex(FAM_ORDER)
    out["family_ratio"] = R[known & R.ok].pivot_table(index="family", columns="algorithm",
                                                      values="ratio", aggfunc="mean").reindex(FAM_ORDER)
    return out


def selection_report(datadir="data", outdir="reports") -> dict:
    outdir = Path(outdir)
    fig_dir = outdir / "figures"
    data = S.load(datadir)
    res = S.evaluate_all(data)
    out = {"results": res}
    lab = {t: S.labels(data.cost[t], data.times, S.penalty_of(t, data)) for t in S.TASKS}
    out["label_dist"] = {t: lab[t].value_counts().to_dict() for t in S.TASKS}
    out["label_by_family"] = {t: pd.crosstab(data.inst.loc[data.cost[t].index, "family"],
                                             lab[t]).reindex(FAM_ORDER)
                              for t in S.TASKS}
    out["trees"] = {}
    out["cost_trees"] = {}
    out["importances"] = {}
    for t in S.TASKS:
        ct, Xc = S.fit_cost_tree(data, t, "structural", depth=3)
        out["cost_trees"][t] = {"text": ct.export_text(), "usage": ct.feature_usage()}
        m, X, y = S.fit_interpretable(data, t, "structural", depth=3)
        out["trees"][t] = {"text": export_text(m, feature_names=list(X.columns), decimals=3),
                           "train_acc": float(m.score(X, y))}
        fig, ax = plt.subplots(figsize=(16, 7))
        plot_tree(m, feature_names=list(X.columns), class_names=list(m.classes_), filled=True,
                  impurity=False, proportion=False, fontsize=8, ax=ax)
        ax.set_title(f"Accuracy-objective CART tree -- task '{t}' (structural features, depth 3)")
        fig.tight_layout(); fig.savefig(fig_dir / f"tree_{t}.png", dpi=110); plt.close(fig)
        imp = S.importances(data, t, "all")
        out["importances"][t] = imp
        fig, ax = plt.subplots(figsize=(7, 5))
        top = imp.head(12)[::-1]
        ax.barh(top.index, top["perm_mean"], xerr=top["perm_std"], color="tab:green")
        ax.set_title(f"Permutation importance -- task '{t}'")
        fig.tight_layout(); fig.savefig(fig_dir / f"importance_{t}.png", dpi=120); plt.close(fig)
    res = out["results"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4), sharey=True)
    for ax, t in zip(axes, ["certified", "optimum", "budgeted"]):
        d = res[(res.task == t)]
        piv = d.pivot_table(index="model", columns=["protocol", "features"], values="gap_closed")
        piv = piv.reindex(list(S.MODELS))
        piv.plot.bar(ax=ax, width=0.8)
        ax.axhline(0, color="k", lw=0.8); ax.axhline(1, color="k", lw=0.8, ls=":")
        ax.set_ylim(-1, 1.05); ax.set_title(f"gap closed -- {t}")
        ax.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(fig_dir / "selection_gap_closed.png", dpi=120); plt.close(fig)
    return out


def _md(df: pd.DataFrame, floatfmt=".3f") -> str:
    return df.to_markdown(floatfmt=floatfmt)


def write_report(datadir="data", outdir="reports") -> Path:
    outdir = Path(outdir)
    th = analyse(datadir, outdir)
    se = selection_report(datadir, outdir)
    meta = json.loads((Path(datadir) / "meta.json").read_text())
    L = ["# AACP -- auto-generated results", "",
         f"Instances: {meta['n_instances']}, budget {meta['budget']} s per run "
         f"(PAR10 penalty {10 * meta['budget']:.0f} s), {meta['jobs']} parallel workers.", "",
         "Regenerate with `python -m aacp analyze`. The interpretation lives in `REPORT.md`.", "",
         "## 1. Portfolio overview", "", th["portfolio_table"].to_markdown(index=False), "",
         "### Median time [s] by family (solved runs)", "", _md(th["family_time"], ".4f"), "",
         "### Fraction solved within budget", "", _md(th["family_solved"], ".2f"), "",
         "### Mean approximation ratio", "", _md(th["family_ratio"], ".3f"), "",
         "## 2. Theory vs practice", ""]
    for key in ("td_dp", "bnb", "ilp", "greedy", "matching", "lp_round", "nt_flow"):
        d = dict(th[key])
        rules = d.pop("stump_rules", None)
        L += [f"### {key}", "", "```json", json.dumps(d, indent=2, default=str), "```", ""]
        if rules:
            L += ["Depth-2 regression tree on greedy ratio (non-trap instances):", "",
                  "```", rules, "```", ""]
    L += ["Figures: `figures/A_td_dp_width.png`, `figures/B_bnb_nodes.png`, "
          "`figures/C_ilp_gap.png`, `figures/D_greedy.png`, `figures/E_two_approx.png`", "",
          "## 3. Algorithm selection", ""]
    res = se["results"].copy()
    L += ["![gap closed](figures/selection_gap_closed.png)", "",
          "Gap closed = (SBS - AS) / (SBS - VBS); 1 = oracle, 0 = no better than always "
          "running the single best solver (NaN when VBS is within 0.1% of SBS, i.e. there is "
          "no selection problem). Accuracy is measured on instances where some algorithm "
          "succeeds. Costs are mean PAR10 seconds (certified / optimum), mean |C|/OPT with a "
          f"penalty of {S.BUDGET_PENALTY} for missing the {S.TAU * 1000:.0f} ms budget "
          "(budgeted), or mean approximation ratio (approx). AS_feat adds feature time.",
          "", res.to_markdown(index=False, floatfmt=".4f"), ""]
    for t in S.TASKS:
        L += [f"### Task `{t}`", "", f"Label distribution: `{se['label_dist'][t]}`", "",
              "Oracle label by family:", "", se["label_by_family"][t].fillna(0).astype(int).to_markdown(), "",
              "Regret-minimising tree (depth 3, structural features; leaf cost in task units):", "",
              "```", se["cost_trees"][t]["text"], "```", "",
              f"Cost-tree feature usage (share of total regret reduction): "
              f"`{ {k: round(v, 3) for k, v in se['cost_trees'][t]['usage'].items()} }`", "",
              f"Accuracy-objective CART tree (train acc {se['trees'][t]['train_acc']:.3f}):", "",
              "```", se["trees"][t]["text"], "```", "",
              "Top permutation importances (forest, all features):", "",
              se["importances"][t].head(10).to_markdown(floatfmt=".4f"), "",
              f"![tree](figures/tree_{t}.png)", ""]
    p = outdir / "results.md"
    p.write_text("\n".join(L))
    res.to_csv(outdir / "selection_results.csv", index=False)
    return p
