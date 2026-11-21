# Research property references for the four supplied cases

The production ethanol/water adapter keeps its existing domain. The two additional
adapters are restricted research extensions, enabled only by the explicit
`research_scope_low_pressure_vle` assumption and task pressure 106.325 +/-0.025 kPa.
They do not constitute full industrial property-package qualification.

`benzene_toluene/reference.xml` is NIST ThermoML for
[Lee et al., Fluid Phase Equilibria (2009)](https://trc.nist.gov/ThermoML/10.1016/j.fluid.2009.03.012.html).
Only dataset 1, measured benzene/toluene P-x-T, is extracted. The 22 points at
333.15/353.15 K give maximum relative pressure error 2.3819% for Raoult with
McGarry vapor pressures (research acceptance 5%). The hotter column region is an
explicit extrapolation, and measured vapor composition is not checked by that set.

`methanol_water/reference.xml` is NIST ThermoML for
[Soujanya et al., JCT (2010)](https://trc.nist.gov/ThermoML/10.1016/j.jct.2009.11.020.html).
Dataset 7 contains methanol (compound 2)/water (compound 3). Only the 11 measured
bubble-temperature points at 95.3 kPa are used for this diagnostic. Default
ChemSep NRTL fails the 1 K screen: maximum error 2.1052 K. That pressure is not
admitted for design, and the discrepancy remains unresolved in the evidence.

`methanol_water/atmospheric_reference.json` transcribes only the 26 methanol/water
T-x-y measurements in Table 2 of
[Alvarez et al., Physics and Chemistry of Liquids (2011)](https://doi.org/10.1080/00319100903012403).
The PDF is available on an author's institutional page, is downloaded locally and
hash verified, and is ignored by git; no publisher-PDF redistribution license is
asserted. The table's printed T(K) header conflicts with its numerical values.
Visual inspection confirms values 64-100, which are explicitly converted from
degrees Celsius using +273.15. No silent correction is made. Unchanged ChemSep
parameters give maximum errors 0.4247 K and 0.006702 in vapor mole fraction at
101.3 kPa; acceptance remains 1 K / 0.025. Operation at 106.325 kPa is a 4.96%
research pressure extrapolation. This dataset was examined after the 95.3 kPa
discrepancy; the exercise is exploratory, not a preregistered holdout evaluation.

No parameters are fitted to these four designs or to either reference set. Every
direction of the ChemSep NRTL binary parameters must exist explicitly. The model
uses tau=b/T in K, alpha from ChemSep, ideal vapor and no Poynting correction.
Pure McGarry correlation limits are enforced without pure-property extrapolation.
The compilation does not publish the original NRTL fit-temperature interval;
project guards are not presented as such an interval.

Fetch missing source files: `python scripts/fetch_case_property_sources.py`.
Re-extract reference subsets: `python scripts/qualify_case_properties.py`.
All source hashes are in the adjacent JSON files. A failed hash or missing source
blocks the new adapter. Native five-point DWSIM VLE comparisons at the task
pressures pass the separate 0.5 K / 0.01 cross-implementation screen for these
cases. Shared ChemSep parameters prevent calling this independent experimental
confirmation. Runtime evidence retains numerical errors and limitations.
