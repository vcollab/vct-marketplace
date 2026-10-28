# Post-Processing & VCollab Reference

## Result Quantity Interpretation

### Stress Results
| Quantity | Symbol | Interpretation |
|----------|--------|----------------|
| Von Mises Stress | σ_vm | Yielding criterion for ductile metals; compare to yield strength |
| Max Principal Stress | σ₁ | Tensile failure criterion for brittle materials |
| Min Principal Stress | σ₃ | Compressive failure; important for concrete, ceramics |
| Shear Stress (Max) | τ_max | (σ₁ - σ₃)/2; Tresca criterion |
| Hydrostatic Stress | σ_h | (σ₁+σ₂+σ₃)/3; triaxiality indicator for ductile fracture |

### Strain Results
| Quantity | Symbol | Use |
|----------|--------|-----|
| Elastic Strain | EPEL | Reversible; proportional to stress |
| Plastic Strain | PEEQ / EPPL | Permanent deformation; > 0 means yielded |
| Equivalent Total Strain | EPTO | EPEL + EPPL |
| Creep Strain | EPCR | Time-dependent at elevated temperature |

### Displacement & Deformation
- **Deformation scale factor:** Always check! A 100x scale factor can make tiny vibrations look catastrophic
- Confirm actual max displacement value in the legend
- Check deformation direction matches applied load physics

### Contact Results
- **Contact pressure:** Should be compressive (negative in some codes); zero in open regions
- **Contact status:** Open / Closed / Sliding — look for unexpected open contact regions
- **Sliding distance:** For wear assessment; large sliding = potential seizure or fretting

### Thermal Results
- **Temperature distribution:** Verify boundary condition temperatures appear at correct nodes
- **Heat flux:** Direction matters; check magnitude against hand-calc q = k × ΔT/L
- **Thermal gradient:** High gradient = high thermal stress risk

### CFD Results
- **Velocity magnitude:** Check for separation zones, recirculation, wake patterns
- **Pressure:** Stagnation pressure at leading edge; suction peaks on airfoils/ducts
- **Wall shear stress:** Indicator of separation (τ_w → 0 at separation point)
- **Turbulence kinetic energy (TKE):** High TKE in shear layers, wakes
- **y+:** Verify it matches the wall treatment used (see domains.md)
- **Streamlines:** Should follow physical flow path; crossing streamlines = unsteady or 3D effects

---

## Detecting Artifacts and Modeling Errors

### Stress Singularities
**What:** Mathematically infinite stress at geometric discontinuities (sharp corners, point loads, point constraints)
**How to detect:**
- Stress increases monotonically as mesh is refined
- Peak at 1–2 elements away from constraint/corner
- No convergence in mesh study

**What to do:**
- Add fillet radius (if geometry allows)
- Use sub-modeling to isolate critical region
- Use stress linearization (pressure vessel standard)
- Accept singularity if it's a numerical artifact, not a real stress raiser

### Rigid Body Motion
**Symptoms:** Very large displacement (1e10+), solver divergence, zero-energy modes
**Causes:** Missing or incorrect boundary conditions; floating substructure
**Fix:** Check all DOFs are constrained; use weak springs if needed

### Overconstraint
**Symptoms:** Artificially low stress near constraints; non-physical reaction moments
**Example:** Fully-fixed base of a thin plate in bending → artificial stress concentrations
**Fix:** Use appropriate constraint (pin, roller, symmetry BC); avoid over-constraining

### Hourglass Modes (Explicit)
**Symptoms:** Irregular "hourglassing" mesh deformation pattern; hourglass energy > 5% total
**Fix:** Use hourglass control (stiffness-based or viscous); refine mesh; use full integration selectively

### Contact Penetration
**Symptoms:** Physically impossible overlap of parts in result visualization
**Fix:** Increase penalty stiffness; use Lagrange multiplier; check contact pair definition

---

## VCollab Workflows

### VCollab RRR (Result Review Report)

VCollab RRR is an interactive HTML/3D report format for sharing CAE results without requiring solver licenses.

**When reviewing RRR reports:**

1. **Verify completeness:**
   - All required load cases present?
   - All result types included (stress, displacement, strain, fatigue life)?
   - All critical regions visible with appropriate viewpoints?

2. **Check visualization settings:**
   - Color map legend: Is range appropriate? Auto-scaled legends can hide critical values
   - Verify legend max matches material yield/ultimate for stress results
   - Deformation scale factor: Confirm actual displacement value is reported separately

3. **Probe measurements:**
   - Spot-check critical node/element values against solver output
   - Verify probe locations are at engineering-critical points (not arbitrary)

4. **Animation frames:**
   - For dynamic results, confirm animation captures peak response
   - For nonlinear, confirm load steps capture critical deformation stages

5. **Section cuts:**
   - Interior stress distribution — confirm cut plane aligns with stress gradient direction

### .cax Files (VCollab CAX Format)

VCollab's binary compressed format containing model geometry + simulation results.

**Review checklist:**
- Open in VCollab Pro or VCollab Presenter
- Check dataset list: Confirm all load cases and result types are exported
- Verify time steps/increments are complete (no truncated results)
- Check measurement sets — engineering-defined probes at critical locations
- Compare result range in .cax against original solver output (no data loss in compression)

**Common issues:**
- Missing datasets due to export settings → regenerate from solver
- Coarse display mesh (visual only) vs. fine FEA mesh → confirm result interpolation is correct
- Color averaging on display mesh may smooth out peak values → always check probe values

### .wcax Files (Web CAX)

Web-optimized version of .cax for browser-based viewing (no plugin required).

**Additional checks:**
- Verify .wcax was generated from the same source as .cax (no version mismatch)
- Test in target browser (Chrome recommended for WebGL performance)
- Confirm all interactive features work: rotation, probe, animation, section cut
- Large model warning: .wcax > 500MB may have performance issues in browser; consider model simplification
- Check that result fidelity matches .cax (wcax uses additional compression — verify no significant result degradation)

**Sharing/compliance:**
- .wcax can be opened by anyone with a browser — confirm no proprietary data exposure risk
- Recommend adding watermark and report metadata (project, revision, date, responsible engineer)

---

## Engineering Validation Checklist

Before accepting any CAE result:

- [ ] Mesh convergence study performed?
- [ ] Boundary conditions reviewed against physical setup?
- [ ] Material properties verified (units, temperature dependence)?
- [ ] Solver convergence confirmed (residuals, energy balance)?
- [ ] Results compared to hand calculations or test data?
- [ ] Stress singularities identified and addressed?
- [ ] Safety factor computed against appropriate failure criterion?
- [ ] Sensitivity study on critical parameters?
- [ ] Sign convention checked (tensile positive, compressive negative)?
- [ ] Report includes all required load cases?
- [ ] VCollab output verified against solver output?
