# Adaptive Algorithm Selection via Learned Complexity Prediction
### An empirical study of worst-case bounds vs. instance structure for Minimum Vertex Cover

*DAA course project. All numbers below come from the committed run in `data/`
(648 instances × 7 algorithms). The full auto-generated tables are in
[`reports/results.md`](reports/results.md).*

---

## Abstract

Textbook analysis ranks algorithms by their worst-case bounds. In practice, which
algorithm is best depends on the *instance*. We study this gap for Minimum Vertex
Cover (MVC) using a seven-algorithm portfolio: tree-decomposition DP, branch & bound,
ILP, greedy, maximal matching, LP rounding, and a max-flow (König / Nemhauser–Trotter)
method. We run it on 648 graphs from nine families, each family built to vary one
structural property (density, degree heterogeneity, clustering, treewidth,
bipartiteness, community structure, and an adversarial greedy gadget).

We find three things:

1. **Effort tracks structural "gap" parameters, not the parameters in the textbook
   bounds.** B&B effort follows the above-LP gap *k* − LP\* (Spearman ρ = 0.64), not
   *n* (ρ = 0.00) and only weakly *k* (ρ = 0.37). ILP time follows the integrality gap
   (ρ = 0.84), not *n* (ρ = 0.30).
2. **Greedy fails in the opposite regime from the one commonly assumed.** Greedy is
   *most* reliable at high clustering. It fails on degree-homogeneous, assortative
   graphs. Its tight logarithmic worst case is extremely fragile: 1–3% random edges
   remove it entirely.
3. **The selector's training objective matters more than its model class.** A single
   depth-4 decision tree trained to minimise regret instead of misclassification
   closes 80% of the gap between the single best solver and the per-instance oracle.
   When misclassification costs are asymmetric, accuracy-trained trees do *worse* than
   no selection at all. Learned selectors, however, do not transfer reliably to graph
   families absent from training.

---

## 1. Problem and portfolio

MVC: given *G* = (*V*, *E*), find the smallest *C* ⊆ *V* that touches every edge. It is
NP-hard, and it can be solved or approximated with every paradigm in the syllabus.

| algorithm | paradigm (unit) | guarantee | implementation notes |
|---|---|---|---|
| `td_dp` | DP on a tree decomposition (III) | O(2^tw · tw · n), exact | min-fill decomposition; tables f_t(S) over bag subsets, vectorised bitmasks; state budget 2^23 |
| `bnb` | backtracking + B&B (IV) | O*(1.4656^k), exact | branch v / N(v); degree-0/1/triangle and Buss rules; maximal-matching lower bound; greedy incumbent |
| `ilp` | integer programming (VI) | exponential, exact | HiGHS branch & cut via `scipy.optimize.milp` |
| `greedy` | greedy (IV) | ratio ≤ H(Δ) | repeatedly take a max-degree vertex |
| `matching` | greedy matching (IV) | ratio ≤ 2 | Gavril: both endpoints of a maximal matching |
| `lp_round` | LP relaxation (VI) | ratio ≤ 2 | dual simplex → half-integral vertex; round x ≥ ½ |
| `nt_flow` | max-flow (V) | exact if bipartite, else ≤ 2 | own Dinic; König cover from the min cut; otherwise the LP optimum via König on the bipartite double cover (Nemhauser–Trotter), keep V₁, greedy on the ½-kernel |

`nt_flow` connects Units V and VI. The VC LP relaxation equals half the minimum
vertex cover of the bipartite double cover, so the LP is solved *combinatorially* by
max-flow, without a simplex solver.

All algorithms are checked against brute force on random small graphs (`tests/`).
In the benchmark, every returned cover is verified, and all exact solvers that finish
must agree on OPT (enforced by an assertion).

## 2. Instances and features

**Nine families, each varying one knob.** All graphs have n ∈ [30, 200] and are
randomly relabelled, so that index-based tie-breaking cannot exploit construction order.

| family | knob | median n / m | median clustering | median tw bound |
|---|---|---|---|---|
| `er` Erdős–Rényi | density p ∈ [0.03, 0.6] | 111 / 586 | 0.14 | 50.5 |
| `ba` Barabási–Albert | power-law degree tail | 120 / 277 | 0.12 | 18 |
| `ws` Watts–Strogatz | clustering via rewiring β | 116 / 264 | 0.31 | 18 |
| `plc` Holme–Kim | clustering at fixed power-law degrees | 121 / 299 | 0.37 | 13.5 |
| `rgg` random geometric | spatial locality | 95 / 404 | 0.64 | 13 |
| `ktree` partial k-trees | treewidth ≤ k ∈ {2, …, 14} | 112 / 483 | 0.71 | 7 |
| `bipartite` | König applies | 100 / 289 | 0 | 23.5 |
| `sbm` stochastic block model | communities ("network segments") | 96 / 509 | 0.24 | 32 |
| `trap` Johnson gadget | adversarial for greedy, plus noise | 67 / 350 | 0 | 20 |

**Features** (`aacp/features.py`):
- 21 *structural* features: size, density, degree CV / skew / max-ratio, clustering,
  transitivity, assortativity, components, degeneracy, a min-degree treewidth bound,
  the normalised-Laplacian spectral gap λ₂ (`lap_gap`), a spectral bipartiteness
  measure 2 − λ_max, the adjacency λ₁ ratio, and a bipartite flag.
- 4 *probing* features (SATzilla-style: run a cheap polynomial algorithm and record
  what it saw): LP\*/n, the half-integral and integral fractions of the NT solution,
  and the `sandwich_gap` = greedy cover / max(maximal matching, ⌈LP\*⌉).

Median feature cost is 14.5 ms (structural) plus 3.0 ms (probing).

## 3. Setup

- Budget: 5 s per (instance, algorithm). The deadlines are cooperative, the DP also
  has a state budget, and HiGHS uses its own time limit. Runs under 50 ms are repeated
  3× and the minimum is kept. Three parallel workers were used.
- OPT is known for 628/648 instances: 613 from the portfolio and 15 from a 60 s ILP
  reference run. The remaining 20 (dense ER/SBM) have only a best-known value. They
  are excluded from every metric that needs OPT.
- **Selection tasks.**
  - `certified`: PAR10 time until an optimum is *proved*.
  - `optimum`: PAR10 time until the cover *is* optimal, proved or not, so a lucky
    heuristic wins.
  - `budgeted`: |C|/OPT achieved within 50 ms (penalty 3).
  - `approx`: |C|/OPT among the four polynomial algorithms.
- **Selectors.**
  - CART tree (depth 4) and random forest trained on the oracle label.
  - **Regret-minimising tree** (`aacp/costtree.py`): each split minimises the total
    cost of the chosen algorithm, and each leaf runs the cheapest algorithm for its
    region.
  - A bagged forest of such trees.
  - An empirical hardness model (EHM): one random-forest regressor of log-cost per
    algorithm; run the argmin (SATzilla-style).
- **Metrics.**
  - SBS = single best solver, chosen on the training folds.
  - VBS = per-instance oracle.
  - Gap closed = (SBS − AS)/(SBS − VBS).
  - Two protocols: stratified 5-fold CV, and leave-one-family-out (LOFO).

## 4. Theory vs. practice

### 4.1 Tree-decomposition DP: the exponent is in tw, but the constant hides it
*Figure: `reports/figures/A_td_dp_width.png`*

- **State count.** It grows as 2^(0.73·w) (R² = 0.89), not 2^w. Only a few bags reach
  the maximum width; the rest are smaller. The O(2^tw · n) bound is a sum dominated by
  its largest terms.
- **Wall time.** It grows much more slowly at small width: slope 0.32 per unit of w
  overall, 0.55 for w ≥ 8. Time correlates better with *m* (ρ = 0.84) than with *w*
  (ρ = 0.63). Below w ≈ 8, the *polynomial* cost of building the min-fill
  decomposition dominates, and the exponential term only takes over later. Big-O
  hides exactly this cross-over.
- **Cliff.** Every instance with heuristic treewidth ≤ 19 was solved. Failures start at
  tw = 20 (median failing tw = 37). This cliff is the 2^w term meeting our 2^23 state
  budget, i.e. memory. It is the bound itself, made visible.
- **The cheap min-degree treewidth feature is a faithful proxy** for the min-fill
  width the DP actually uses (ρ = 0.99).
- **Cheeger link.** The normalised-Laplacian spectral gap correlates with treewidth/n
  (ρ = 0.63). Below λ₂ = 0.154 the DP succeeds 79% of the time; above it, 50%.
  Expanders (large λ₂) have linear treewidth, and Cheeger's inequality ties a small λ₂
  to sparse cuts, i.e. small separators. This is why the learned selector's **root
  split is on λ₂** (§5.3), even though the DP's bound is stated in tw.

### 4.2 Branch & bound: the worst-case parameter is the wrong parameter
*Figure: `reports/figures/B_bnb_nodes.png`*

- **Worst case vs. observed.** The worst case is 1.4656^k nodes. Fitting log-nodes
  against *k* gives an empirical base of 1.05 per unit of k, and with R² = 0.21 *k*
  explains little.
- **Correlates of search-tree size.**

  | variable | Spearman ρ with #nodes |
  |---|---|
  | n | **0.00** |
  | density | 0.12 |
  | k (cover size, the FPT parameter) | 0.37 |
  | **k − LP\*** (above-LP gap) | **0.64** |

  This matches the parameterized-complexity literature: VC parameterised *above the
  LP bound* is FPT (Lokshtanov et al.), so the gap above LP, not k, measures how much
  combinatorial search is really needed.
- **Reductions do most of the work.** 47% of solved instances never branch: reductions
  plus the matching bound settle them at the root.
- **A testable prediction.** On the `trap` family k − LP\* = 0 (bipartite, so LP is
  integral), yet B&B still explores up to about 10³ nodes. Our bound is the *maximal*
  matching, which is weaker than LP, and the greedy incumbent is bad by construction
  there. Using the LP (or `nt_flow`) bound at each node should collapse these trees.
  The data points to the specific engineering fix.

### 4.3 ILP: hardness is the integrality gap
*Figure: `reports/figures/C_ilp_gap.png`*

- ILP time correlates with OPT − LP\* (ρ = 0.84), much less with *n* (ρ = 0.30), and
  not with density (ρ = 0.06).
- 94% of the ILPs HiGHS solves close at the root node. Solved instances average an
  integrality gap of 6.6, timeouts 41.9. (For the 20 timeouts without a proven OPT,
  this gap is an upper bound.)
- ILP is the exact solver of choice exactly when the LP is tight. This is also why
  `lp_ratio` and `sandwich_gap` are useful probing features.

### 4.4 Greedy: the clustering hypothesis is refuted, and the worst case is fragile
*Figure: `reports/figures/D_greedy.png`*

Our starting hypothesis was that greedy "degrades when clustering exceeds X". The
data says the opposite. On non-trap instances:

| clustering | mean ratio | P(greedy suboptimal) |
|---|---|---|
| ≤ 0.05 | 1.041 | 0.56 |
| 0.05–0.2 | 1.036 | 0.86 |
| 0.2–0.4 | 1.032 | 0.77 |
| 0.4–0.6 | 1.029 | 0.67 |
| **> 0.6** | **1.008** | **0.27** |

The features that really drive greedy's error are degree heterogeneity and
assortativity:

| degree CV | P(subopt) | | assortativity | P(subopt) |
|---|---|---|---|---|
| ≤ 0.2 | 0.98 | | ≤ −0.3 | 0.09 |
| 0.2–0.4 | 0.92 | | −0.3 to −0.15 | 0.54 |
| 0.4–1.0 | ≈0.51 | | −0.15 to 0 | 0.91 |
| > 1.0 | 0.20 | | > 0 | ≈0.9 |

Spearman correlations with the ratio: assortativity +0.64, degree CV −0.60, clustering
−0.28. A depth-2 regression tree on the ratio splits on assortativity first.

**Why.** A vertex of degree > *k* must be in every cover of size *k* (Buss' rule).
In heterogeneous, disassortative graphs, hubs attach to low-degree vertices, so
"take the max-degree vertex" is usually a *forced* move, and greedy is near-optimal.
In high-clustering graphs, the cover is dominated by local cliques (a clique of size
*s* needs *s* − 1 vertices), and greedy's local choices are consistent with that.
Greedy fails when degrees are homogeneous: its decisions become tie-breaks, and an
early mistake cannot be undone. Johnson's trap is the extreme case. It is bipartite
(clustering 0), with degrees engineered so that greedy's preference is wrong at
every step.

**The worst case is real but fragile.**
- **Tightness.** On the exact trap, greedy's ratio follows the H(k) − 1 curve:
  1.50, 1.92, 2.13, 2.50, 2.72, 2.95 for k = 8 … 40. This is the largest ratio in the
  whole study.
- **Bound never violated.** Greedy never exceeds H(Δ); the largest observed ratio is
  0.69 × H(Δ).
- **Fragility.** Adding each possible L–R edge with probability 1% drops the ratio to
  1.00 for k ≥ 32. With 3% noise, the trap is gone for k ≥ 16. The trap depends on a
  knife-edge degree ordering (R_i has degree i, L-vertices ≤ i − 1), and random edges
  destroy it. This is a smoothed-analysis-style observation: the logarithmic worst
  case occupies a vanishing neighbourhood of instance space.

### 4.5 The 2-approximations: the bound is 2, the reality is structural
*Figure: `reports/figures/E_two_approx.png`*

- **`matching`** (mean 1.62, max 2.00, never optimal). Its ratio is 2|M|/τ.
  - On König graphs τ = ν, and a greedy maximal matching is nearly maximum, so the
    ratio approaches 2: 1.92 on `bipartite`, 2.00 on `trap`.
  - On dense graphs τ → n, and since 2|M| ≤ n the ratio approaches 1: 1.24 at
    density > 0.3.
  - The property that matters is König–Egerváry-ness, not density itself
    (ρ(ratio, density) = −0.02 across all families).
- **`lp_round`** (mean 1.25, max 1.95).
  - The ratio is driven by the half-integral fraction of the LP vertex (ρ = 0.83). The
    bound (|V₁| + |V_½|)/OPT becomes tight as V_½ grows.
  - It is exact on every bipartite instance: the incidence matrix is totally
    unimodular, so simplex returns an integral vertex.
  - In 36% of instances it certifies its own optimality via ⌈LP\*⌉.
- **`nt_flow`** (mean 1.017, max 1.10).
  - It was never worse than greedy, and strictly better on 19% of instances. It
    certifies optimality on 41%.
  - The NT theorem puts V₁ in some optimal cover, so greedy only ever acts on the
    smaller, harder ½-kernel.
  - Consequence: the `approx` task has **no selection problem**. The single best
    approximation (`nt_flow`) is within 0.01% of the oracle, so gap closed is
    undefined there.

## 5. Learned algorithm selection

### 5.1 Main results (gap closed; 1 = oracle, 0 = always run the SBS, < 0 = worse than the SBS)

| selector | certified CV | optimum CV | budgeted CV | certified LOFO | optimum LOFO | budgeted LOFO |
|---|---|---|---|---|---|---|
| CART tree, accuracy objective | 0.53 | −0.60 | −2.32 | −2.02 | −2.03 | −0.69 |
| random forest, accuracy objective | **1.00** | −0.13 | 0.36 | −1.28 | −2.42 | 0.41 |
| **regret-minimising tree** (depth 4) | 0.80 | 0.66 | 0.62 | −0.96 | −2.69 | −0.42 |
| regret-minimising forest | 0.93 | **0.99** | 0.64 | −0.03 | 0.04 | **0.81** |
| EHM (runtime regression, SATzilla) | 0.92 | 0.80 | **0.72** | **0.52** | 0.00 | 0.60 |

*All features. With structural features only, the CV numbers are: certified 0.52 /
0.93 / 0.80 / 0.93 / 0.80; optimum −1.80 / −1.13 / 0.33 / 0.93 / 0.66; budgeted
−2.41 / 0.25 / 0.56 / 0.62 / 0.73 (same row order as the table).*

**Absolute numbers, certified task (CV).**

| | PAR10 [s] | instances certified |
|---|---|---|
| SBS (always `bnb`) | 3.93 | 92.4% |
| oracle (VBS) | 2.78 | 94.6% |
| best selector (random forest, all features) | 2.78 | 94.6% |
| regret-minimising tree | 3.01 | 94.1% |

Charging feature computation to the selector adds only about 0.03 s per instance.

**Absolute numbers, optimum task (CV).** SBS 2.47 s, VBS 1.27 s, regret-minimising
forest 1.28 s.

### 5.2 Finding: accuracy is the wrong objective when errors are asymmetric

In the `optimum` task the two dominant labels are nearly balanced: greedy 244, bnb
242. Their errors are not.

- Running `bnb` where greedy would have sufficed costs about **1 ms**.
- Running `greedy` where it is suboptimal costs the **50 s** PAR10 penalty.

A classifier that maximises accuracy treats these two errors as equal. So the
accuracy-trained CART tree (77% label accuracy) and forest (86%) are both *worse than
never selecting at all* (gap −0.60 and −0.13). The regret-minimising tree has *lower*
accuracy (74%) but closes 66% of the gap, and its bagged version closes 99%.

The same pattern is even stronger in `budgeted`: CART reaches 73% accuracy and a
−2.32 gap.

The `certified` task is different. Its cost asymmetry is mild: picking the "wrong"
exact solver usually costs milliseconds, and the one catastrophic error, `nt_flow` on
a non-bipartite graph, is trivially separable by `is_bipartite`. There, accuracy-trained
models work too (forest 1.00, CART 0.53).

**Lesson:** an algorithm selector must be trained on the selection objective. The
regret-minimising tree does this while staying a single readable tree.

### 5.3 What the interpretable selector learned (certified task, depth 3, structural features)

```
lap_gap <= 0.154                        (poorly connected: small separators)
|  avg_deg <= 5.67
|  |  deg_skew <= -0.098 -> ilp      (n=5)
|  |  deg_skew >  -0.098 -> bnb      (n=145)    sparse: reductions + bounds win
|  avg_deg > 5.67
|  |  tw_ub <= 18.5   -> td_dp       (n=34)     O(2^tw n) pays off exactly here
|  |  tw_ub >  18.5   -> ilp         (n=44)     too wide for DP, LP still tight-ish
lap_gap > 0.154                         (expander-like)
|  clustering <= 0.0044
|  |  assortativity <= -0.332 -> bnb     (n=60)
|  |  assortativity >  -0.332 -> nt_flow (n=83) bipartite: König max-flow is exact
|  clustering > 0.0044 -> bnb         (n=277)
```

Every split corresponds to a theoretical statement:

- **Root split on λ₂.** A spectral proxy for treewidth, via Cheeger (§4.1).
- **DP leaf at tw ≤ 18.5.** This learned threshold sits just below the empirical DP
  cliff at tw = 20 (§4.1), and it is selected only where the graph is too dense for B&B.
- **Max-flow leaf.** Clustering ≈ 0 combined with non-extreme assortativity identifies
  the bipartite/trap instances, where König makes a Unit-V polynomial algorithm *exact*
  for an NP-hard problem.

In contrast, the accuracy-trained CART tree of the same depth predicts `bnb` in 7 of
its 8 leaves.

For the `budgeted` task, the regret-minimising tree's first split is clustering > 0.593,
and its large high-clustering, assortative leaf runs `greedy`. This independently
rediscovers the §4.4 finding that greedy is reliable at high clustering.

### 5.4 Finding: probing features are the most informative

`sandwich_gap` (greedy cover over the best cheap lower bound) has the highest
permutation importance in **every** task. Adding the four probing features (about 3 ms)
improves the optimum-task regret-minimising tree from 0.33 to 0.66 gap closed, and the
EHM from 0.66 to 0.80.

Running a cheap polynomial algorithm is the best predictor of how an expensive one
will behave. This is the "learned complexity prediction" in practice: the sandwich
between a 2-approximation's lower bound and greedy's upper bound directly measures
how much search remains.

### 5.5 Finding: selection does not generalise to unseen structure

Under leave-one-family-out, most selectors are worse than the SBS on the `certified`
and `optimum` tasks. The EHM is the exception on `certified` (0.52), and the cost
forest roughly matches the SBS. Selectors learn family-specific regions of feature
space. A held-out family (e.g. `trap` or `bipartite`) can sit in a region where the
training data recommends the wrong solver.

The `budgeted` task transfers better (cost forest 0.81, EHM 0.60). Whether an
algorithm finishes within 50 ms depends mostly on generic size features (*m*, *n*),
not on family-specific structure.

Practical implication: a deployed selector needs training data that covers the target
distribution, or a fallback to the SBS when an instance is out of distribution.

## 6. Threats to validity

- **Implementation constant factors.** HiGHS (ILP/LP) is compiled C++; everything else
  is Python. Wall-clock labels therefore reflect *these implementations*. This is why
  §4 also reports machine-independent work (`ops`: DP states, B&B nodes, MIP nodes,
  flow phases).
- **Timing noise.** Runs used three parallel workers. Sub-50 ms runs take the minimum
  of 3 repeats. Each instance was benchmarked once.
- **Synthetic, small instances.** n ≤ 200, nine generator families. Real-world graphs
  may occupy other regions of feature space, and §5.5 shows that this matters.
- **Heuristic treewidth.** The DP width is an upper bound (min-fill), so "treewidth"
  means "heuristic width" throughout.
- **Budget artefacts.** The DP cliff in §4.1 is partly by design (state budget 2^23),
  and PAR10 results depend on the 5 s budget.
- **Unknown OPT.** 20 instances have no proven optimum. They are excluded from the
  OPT-based tasks but kept in `certified`, where no solver succeeds on them, so they
  are labelled `unsolved` and excluded from classifier training.

## 7. Future work

- **LP-bounded B&B.** Replace the matching bound with the NT/LP bound and test the
  §4.2 prediction that the search-tree size should then scale with k − LP\*.
- **Security angle.** In a vulnerability or attack graph, a vertex cover is a minimum
  set of hosts to patch or monitor so that every exploit edge is covered. Enterprise
  networks look like SBM segments with hubs (high degree-CV, disassortative). §4.4
  predicts that greedy and reduction-based B&B are strong in that regime, while
  König/NT methods win on two-tier (bipartite) topologies. Validating on real attack
  graphs (e.g. generated with MulVAL) is a natural paper extension.
- **Out-of-distribution detection.** Detect when an instance lies outside the
  training families and fall back to the SBS, motivated by §5.5.

## 8. Reproduce

```bash
pip install -r requirements.txt
```

```bash
python -m pytest -q
```

```bash
python -m aacp benchmark --scale 2 --budget 5 --jobs 3
```

```bash
python -m aacp analyze
```
