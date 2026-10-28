# CAE Domain Knowledge Reference

## 1. Structural Analysis

### Linear Static
- Validity: Small deformation, linear material, no contact nonlinearity
- Check: Is displacement < 10% of characteristic length? If not → geometric nonlinearity required
- Safety factor interpretation: Von Mises / Yield strength (static ductile), Max principal / UTS (brittle)

### Nonlinear Analysis
- **Material nonlinearity:** Plastic strain (EPEL/PEEQ), check for necking, strain localization
- **Geometric nonlinearity (NLGEOM):** Required when deflection > thickness or span/10
- **Contact nonlinearity:** Check penetration, chattering, convergence plots per increment

### Buckling
- **Linear buckling (Eigenvalue):** Load factor = critical load / applied load. Conservative only if prebuckling is linear
- **Nonlinear buckling:** Arc-length or displacement-controlled; watch for negative eigenvalues
- Red flag: Load factor < 3 for thin-walled structures without imperfection sensitivity study

### Modal Analysis
- Natural frequencies and mode shapes; check for rigid body modes (near-zero frequency)
- MAC (Modal Assurance Criterion) for model correlation
- For rotating machinery: Campbell diagram for resonance risk

### Harmonic / Random Vibration
- Q factor (amplification), damping ratio (typical structural: 1-5%)
- PSD inputs: Verify g²/Hz units and frequency range coverage

### Fatigue
- **SN (stress-life):** High cycle, nominally elastic, Basquin equation
- **EN (strain-life):** Low cycle, plastic strain present, Coffin-Manson + Morrow
- **Fracture mechanics:** Paris law, crack growth rate da/dN
- Mean stress correction: Goodman, Gerber, or Morrow depending on material
- Always check: Is the stress state multiaxial? → Use critical plane or von Mises equivalent

### Thermal-Structural
- Check: Is CTE mismatch dominant? → Thermal stress = E × α × ΔT (rough estimate)
- Verify temperature-dependent material properties used for elevated-temperature runs

---

## 2. CFD

### Turbulence Models
| Model | Best Use | Limitation |
|-------|----------|-----------|
| k-ε (Standard) | Fully turbulent, free shear | Poor near walls, adverse pressure gradient |
| k-ε (Realizable) | Swirling flows, round jets | - |
| k-ω SST | Adverse pressure gradient, separation | More expensive |
| LES | Unsteady, large-scale turbulence | Very expensive, requires fine mesh + small dt |
| DES | Separated flows with economy | Transition region sensitivity |

### y+ Interpretation
- **y+ < 1:** Resolve viscous sublayer (needed for SST, transitional models)
- **y+ 30-300:** Wall function regime (acceptable for k-ε with wall functions)
- Mismatch between wall treatment and y+ is a common error → always verify

### Convergence Assessment
- Residuals should drop 3-4 orders of magnitude
- Monitor point values (lift, drag, pressure) for oscillation → indicates unsteady behavior
- Mass/energy imbalance < 0.1% for steady-state

### Boundary Conditions
- Inlet: Specify turbulence intensity (1-5% typical) and length scale or hydraulic diameter
- Outlet: Pressure outlet preferred; zero-gradient if fully developed
- Walls: No-slip; check adiabatic vs. specified heat flux/temperature

---

## 3. Explicit Dynamics (Crash / Impact / Drop Test)

### Time Step Stability (Courant Condition)
- Δt = CFL × L_min / c (c = wave speed = √(E/ρ) for solids)
- Mass scaling: Increases mass of small elements artificially → check % kinetic energy added by mass scaling < 1-2%

### Energy Balance Check (Critical)
- Total energy = Internal energy + Kinetic energy + Hourglass energy + Contact energy
- **Hourglass energy / Total energy < 5%** (red flag if higher → underintegrated element issue)
- **Energy error < 10%** overall

### Hourglass Control
- Caused by single-point integration elements with zero-energy modes
- Remedies: Stiffness-based hourglass (Flanagan-Belytschko), viscous, or full integration

### Material Models for Crash
- **Elastic-plastic with failure:** MAT_24 (LS-DYNA), strain-rate effects (Cowper-Symonds, Johnson-Cook)
- **Foam:** MAT_57 / MAT_83 for energy absorbers
- Always check: Is strain rate sensitivity included for high-speed impact?

---

## 4. Contact Mechanics

### Formulations
| Type | Pro | Con |
|------|-----|-----|
| Penalty | Robust, fast | Allows penetration; stiffness-dependent |
| Lagrange Multiplier | No penetration | Expensive, oscillations possible |
| Augmented Lagrange | Balanced | More iterations |

### Common Issues
- **Penetration:** Too-soft penalty stiffness → increase contact stiffness or use Lagrange
- **Chattering:** Contact opening/closing each iteration → add contact stabilization
- **Overclosure:** Initial geometry interference → adjust clearance or use initial stress state
- **Friction:** μ = 0.1–0.3 (steel/steel lubricated), 0.3–0.5 (dry metal), always question assumed value

---

## 5. Mesh Quality

### Key Metrics
| Metric | Good | Acceptable | Poor |
|--------|------|-----------|------|
| Aspect Ratio | < 3 | < 10 | > 10 |
| Skewness | < 0.25 | < 0.5 | > 0.75 |
| Jacobian | > 0.7 | > 0.5 | < 0.3 |
| Warpage (quads) | < 5° | < 15° | > 30° |

### Hex vs Tet
- **Hex:** Better accuracy per DOF, preferred for bending-dominated problems
- **Tet (linear):** Overly stiff (shear/volumetric locking), use quadratic (10-node) for accuracy
- **Shell:** Appropriate for thin-walled (t/L < 1/10); check FSDT vs. Kirchhoff assumptions

### Mesh Convergence Study
- Mandatory for any design-critical analysis
- Plot max stress/deflection vs. element count; convergence within 5% = acceptable
- Near singularities: Stress never converges → use sub-modeling or stress linearization

---

## 6. Solvers

### Direct vs. Iterative
- **Direct (Sparse direct, MUMPS):** Robust, expensive for large models; good for ill-conditioned systems
- **Iterative (PCG, GMRES):** Scalable; requires good preconditioning; can diverge

### Convergence Criteria
- Force residual norm < 0.1–1% of reference force
- Displacement increment norm < tolerance
- Energy criterion (most robust): < 1e-4 typical

### Divergence Causes
- Rigid body motion (missing constraint)
- Material instability (negative tangent modulus)
- Contact instability (chattering)
- Geometric instability (snap-through without arc-length)
- Numerical ill-conditioning (poor aspect ratio elements)
