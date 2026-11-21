# case-2: Worked calculations — Ethanol/water distillation: 48 wt% ethanol feed

Worked calculations reconstructed from the human engineer's preliminary design.

## 1. Notation and design basis

Component A is the more volatile component; B is the less volatile component. `F`, `D`, and `W` denote feed, distillate and bottoms molar flow in kmol/h. `B` in JSON stream tables is the same bottoms stream as `W` here. Mass fractions are `w`; mole fractions are `x`, with feed mole fraction `zF`. Use `d_c` for shell diameter, to distinguish it from distillate flow `D`.

| Input | Value | Unit / interpretation |
| --- | --- | --- |
| Components A / B | ethanol / water | declared composition order |
| M_A / M_B | 46.07 / 18.015 | kg/kmol; source conversion constants |
| Annual throughput | 16500 | t/year of feed |
| Annual operation | 7920 | h/year |
| w_F / w_D | 0.48 / 0.936 | mass fraction |
| w_W | 0.022 | mass fraction |
| Top pressure | 101.325 | kPa absolute in controlled comparison |
| Feed condition | q=1 | saturated liquid |

Source requirement locations: DOCX P0072 (atmospheric, bubble-point feed), P0078-P0095 (mass specifications and throughput).

For gauge-pressure cases, 5 kPa + 101.325 kPa ambient = 106.325 kPa absolute; the reports generally round this to 106.3 kPa. Atmospheric ethanol/water is normalized to 101.325 kPa.

## 2. Mass-to-mole conversion and material balance

The following is **independent normalization of the original requirements**. It keeps full precision and does not silently substitute the reports' rounded mole fractions.

$$
x_A=\frac{w_A/M_A}{w_A/M_A+(1-w_A)/M_B},\qquad \overline M=x_AM_A+(1-x_A)M_B.
$$

$$
z_F=\frac{0.48/46.07}{0.48/46.07+(1-0.48)/18.015}=0.2652222454.
$$

$$
x_D=\frac{0.936/46.07}{0.936/46.07+(1-0.936)/18.015}=0.8511659462.
$$

$$
x_W=\frac{0.022/46.07}{0.022/46.07+(1-0.022)/18.015}=0.0087195968.
$$

$$
\dot m_F=\frac{16500\times1000}{7920}=2083.33333333\ \mathrm{kg/h}.
$$

$$
F=\dot m_F\left(\frac{w_F}{M_A}+\frac{1-w_F}{M_B}\right)=2083.33333333\left(\frac{0.48}{46.07}+\frac{0.52}{18.015}\right)=81.8411720386\ \mathrm{kmol/h}.
$$

$$
F=D+W,\qquad Fz_F=Dx_D+Wx_W.
$$

$$
D=F\frac{z_F-x_W}{x_D-x_W},\qquad W=F-D,\qquad \eta_A=\frac{Dx_D}{Fz_F}.
$$

$$
D=81.84117204\frac{0.26522225-0.0087196}{0.85116595-0.0087196}=24.91847393\ \mathrm{kmol/h}.
$$

$$
W=56.92269811\ \mathrm{kmol/h},\qquad \eta_A=0.9771334792.
$$

| Quantity | Source-reported | Independent normalized result |
| --- | --- | --- |
| F (kmol/h) | 81.8411 | 81.8411720386 |
| D (kmol/h) | 24.918 | 24.9184739307 |
| W (kmol/h) | 56.923 | 56.9226981079 |
| z_F | 0.2652 | 0.2652222454 |
| x_D | 0.8512 | 0.8511659462 |
| x_W | 0.0087 | 0.0087195968 |

Small differences can arise from intermediate rounding. Source arithmetic, labels and stage formulas must still be checked separately.

## 3. Human equilibrium model, minimum reflux and theoretical stages

This section retains the **human calculation approximation and its source-reported choices**. Replaying an approximate correlation is an arithmetic check, not experimental validation.

Source: DOCX P0177-P0218. The report fits the equilibrium curve locally as

$$
y=0.4723x^3-0.405x^2+0.4727x+0.4582.
$$

For an internal rectifying pinch it uses the tangent condition

$$
\frac{y_e-x_D}{x_e-x_D}=\left.\frac{dy}{dx}\right|_{x_e},\qquad \frac{dy}{dx}=1.4169x^2-0.81x+0.4727.
$$

The printed tangent point is `(x_e,y_e)=(0.7501,0.78423)`; the report uses `x_D=0.8511` in this step.

$$
R_{\min}=\frac{x_D-y_e}{y_e-x_e}=\frac{0.8511-0.78423}{0.78423-0.7501}\simeq1.96,\qquad R=2R_{\min}=3.92.
$$

The inverse equilibrium fit printed for stage stepping is

$$
x=88.83y^6-248.84y^5+253.52y^4-112.84y^3+21.978y^2-1.3965y+0.0166.
$$

$$
x(0.8511)=0.8416812749\quad\text{(recomputed)},\qquad x_1=0.838\quad\text{(source-reported)}.
$$

The reported later liquid fractions include `x2=0.8256`, `x3=0.8440`, and `x4=0.7707`. The increase at stage 3 is inconsistent with the intended descending enrichment sequence. The displayed source sequence does not establish a valid reproducible 20-stage design. We retain the reported 20 stages and feed stage 16 as the human design to be tested; we do not manufacture omitted intermediate steps.

### Operating lines and internal loads

For constant molar overflow and saturated-liquid feed:

$$
L=RD,\quad V=(R+1)D,\quad L_s=L+qF,\quad V_s=V+(q-1)F=V.
$$

$$
L=3.92\times24.918=97.67856;\quad V=(3.92+1)\times24.918=122.59656\quad[\mathrm{kmol/h}].
$$

$$
L_s=97.67856+81.8411=179.51966,\qquad V_s=122.59656\quad[\mathrm{kmol/h}].
$$

These are recomputed from the displayed human R/D/F, not copied rounded internal loads.

$$
y_R(x)=\frac{R}{R+1}x+\frac{x_D}{R+1},\qquad y_S(x)=\frac{L_s}{V_s}x-\frac{W}{V_s}x_W.
$$

$$
y_R(x)=0.7967479675x+0.1730081301.
$$

With a closed split, the stripping line also follows from the feed intersection:

$$
y_q=y_R(z_F),\qquad m_S=\frac{y_q-x_W}{z_F-x_W},\qquad y_S(x)=x_W+m_S(x-x_W).
$$

This intersection form avoids a small discontinuity caused solely by independently rounded source F/D/W. Starting at `y1=xD`, find `x_n` from the equilibrium relation, then set `y_(n+1)=y_R(x_n)` above the feed or `y_S(x_n)` below it. Stop when `x_n<=xW`. The first crossing of `zF` identifies the feed stage in this reconstruction.

Stage convention for comparison: include the partial reboiler and exclude the total condenser. An integer step count is not a physical tray count.

## 4. Human tray-efficiency, pressure and height calculations

The source applies an OConnell-type empirical correlation. In its reported convention, viscosity is inserted numerically in mPa·s (cP), and efficiency is a fraction:

$$
E_O=0.49(\alpha\mu_L)^{-0.245},\qquad N_{\mathrm{actual},s}=\left\lceil\frac{N_{\mathrm{theoretical},s}}{E_{O,s}}\right\rceil.
$$

This reproduces the source's empirical method only. Its applicability and the underlying viscosity/volatility values are not independently qualified here. Global OConnell efficiency is not stagewise Murphree efficiency.

Source: DOCX P0221-P0243, P0278-P0290.

$$
\alpha_m=\sqrt{1.0157\times0.3435}\simeq0.591,\quad
\mu_m=0.265(0.426)+(1-0.265)(0.31876)\simeq0.347.
$$

$$
E_O=0.49(0.591\times0.347)^{-0.245}\simeq0.722.
$$

The source's volatility below unity and nonmonotonic stage data require review; obtaining an arithmetic efficiency does not validate those inputs.

$$
N_{p,R}=\lceil15/0.722\rceil=21,\quad N_{p,S}=\lceil4/0.722\rceil=6,\quad N_p=27.
$$

The actual feed tray is reported as 22. The source gives a body-height expression

$$
H_Z=(27-2-3)0.45+3(0.6)+0.675=12.375\ \mathrm{m}\quad\text{(arithmetic replay)},
$$

while printing **16.9 m**. These two values must remain separate. The replay is not a corrected total tower height: head, skirt and end-space definitions still need a consistent vessel specification.

## 5. Human shell diameter, tray geometry and hydraulic checks

The source uses chart-derived capacity factors and source-reported transport properties. The formulas below explain that calculation path; chart readings, material properties and empirical bounds remain unverified source inputs.

$$
\dot V=\frac{V\overline M_V}{3600\rho_V},\qquad \dot L=\frac{L\overline M_L}{3600\rho_L}\quad[\mathrm{m^3/s}].
$$

$$
F_{LV}=\frac{\dot L}{\dot V}\sqrt{\frac{\rho_L}{\rho_V}},\quad C=C_{20}\left(\frac{\sigma}{20}\right)^{0.2},\quad u_f=C\sqrt{\frac{\rho_L-\rho_V}{\rho_V}}.
$$

Here the empirical surface-tension correction uses sigma numerically in mN/m and the reference 20 mN/m. The allowable velocity `u=k u_f` uses the source-selected capacity fraction `k`.

$$
d_c=\sqrt{\frac{4\dot V}{\pi u}},\qquad A_T=\frac{\pi d_c^2}{4},\qquad u_{\mathrm{actual}}=\frac{\dot V}{A_T}.
$$

Source locations: DOCX P0245-P0277, P0293-P0364. The following representative rectifying-section substitution uses displayed source inputs:

$$
u_f=0.08\sqrt{\frac{840.142-1.145}{1.145}}=2.16554617\ \mathrm{m/s},\qquad u=0.65u_f=1.40760501\ \mathrm{m/s}.
$$

$$
d_{c,\mathrm{calc}}=\sqrt{\frac{4(1.052)}{\pi(1.40760501)}}=0.97548934\ \mathrm{m}.
$$

The source selects shell diameter **1.0 m** after its section checks. The calculation just shown is a replay of one section, not a new independent shell rating.

### Weir and downcomer

$$
l_w=f_wd_c,\quad h_{ow}=\frac{2.84}{1000}E\left(\frac{3600\dot L}{l_w}\right)^{2/3},\quad h_w=h_L-h_{ow}.
$$

$$
l_w=0.7\times1.0=0.7\ \mathrm{m},\qquad h_{ow}(E=1)=0.00923403\ \mathrm{m}.
$$

The replay sets E=1 for the displayed comparison. The ethanol source instead selects E=1.02 and rounds the liquid head to 10 mm; these choices must not be interchanged silently.

$$
A_f=f_AA_T,\qquad \theta=\frac{A_fH_T}{\dot L},\qquad u_d=\frac{\dot L}{A_f}.
$$

$$
A_T=\frac{\pi(1.0)^2}{4}=0.78539816\ \mathrm{m^2},\quad A_f=0.0877A_T=0.06887942\ \mathrm{m^2},\quad \theta=\frac{0.06887942(0.45)}{0.00114}=27.18924431\ \mathrm{s}.
$$

The normalized rounded shell area above can differ from a source area carried forward before rounding. Residence time checks only the stated geometry/flow arithmetic, not downcomer operability.

$$
h_0=\frac{\dot L}{l_wu_{dc}}\quad\text{or the source-selected rule }h_0=h_w-0.006\ \mathrm{m}.
$$

### Valve layout and hydraulic operating window

$$
F_0=u_0\sqrt{\rho_V},\qquad N_v=\frac{\dot V}{(\pi d_0^2/4)u_0},\qquad \phi=\frac{N_v\pi d_0^2/4}{A_T}.
$$

The source uses valve-hole diameter `d0=0.039 m` and nominal hole factor `F0=10`. Its arranged valve count for the representative section is 83. The empirical F0 unit is `(m/s) sqrt(kg/m3)`; it is not a dimensionless friction factor.

$$
h_c=\xi\frac{\rho_Vu_0^2}{2g\rho_L},\qquad h_p=h_c+\beta h_L+h_\sigma,\qquad h_d=0.153\left(\frac{\dot L}{l_wh_0}\right)^2.
$$

$$
H_{dc}=h_p+h_d+h_L<\varphi(H_T+h_w).
$$

These liquid-head expressions require all lengths in m. The source uses valve-specific dry-pressure-drop coefficients near 5.34-5.37 for the stated regime and an aeration factor near 0.5. They must not be applied outside that regime without supporting data.

$$
\dot L_{\max}=\frac{A_fH_T}{\theta_{\min}},\qquad \dot L_{\min}=\frac{l_w}{3600}\left(\frac{1000h_{ow,\min}}{2.84E}\right)^{3/2}.
$$

The source constructs the operating window from minimum weir head, downcomer residence time, minimum valve-hole factor, entrainment and downcomer flooding. A standard transcription of its entrainment index is

$$
f_{\mathrm{ent}}=\frac{\dot V\sqrt{\rho_V/(\rho_L-\rho_V)}+1.36\dot L Z_L}{K_FC_FA_b}.
$$

The chart factor CF, path length ZL, bubbling area Ab and property correction KF must refer to the same section. This note does not certify a flooding/entrainment margin from the source's graphs.

**Arithmetic discrepancy:** DOCX P0310 gives `h0=37.558 mm` from operands `0.0011/(0.7×0.15)`. Those operands give

$$
h_0=0.01047619\ \mathrm{m}=10.47619\ \mathrm{mm},
$$

not 37.558 mm. The later hydraulic checks must therefore not be treated as independently passed. The report also mixes pre-rounding areas and different vapor flow values in its diameter section.

## 6. Human condenser, reboiler, utilities and nozzles

For source latent heats in kJ/kg and molar masses in kg/kmol, the mixture molar latent heat is in **kJ/kmol**, not kJ/mol:

$$
\overline\lambda=\sum_i x_iM_i\lambda_i,\qquad Q_{\mathrm{lat}}=\frac{\dot n\overline\lambda}{3600}\quad[\mathrm{kW}].
$$

This latent-only estimate is not a complete enthalpy balance and does not verify the latent-heat source or temperature range. For the entire column, with condenser heat removed and reboiler heat supplied taken positive:

$$
\frac{Fh_F}{3600}+Q_R=\frac{Dh_D+Wh_W}{3600}+Q_C.
$$

Here F/D/W are in kmol/h, h is in kJ/kmol, and Q is in kW; the factors of 3600 keep all terms on the same basis.

$$
\dot m_{cw}=\frac{Q_C}{c_{p,cw}(T_{cw,out}-T_{cw,in})},\qquad \dot m_{steam}=\frac{Q_R}{\lambda_{steam}}.
$$

$$
\Delta T_{lm}=\frac{\Delta T_1-\Delta T_2}{\ln(\Delta T_1/\Delta T_2)},\qquad A=\frac{1000Q}{U\Delta T_{lm}}.
$$

Here Q is kW, U is W/(m2 K), and A is m2. A chosen fouling or heat-loss allowance must be recorded explicitly; a larger catalog area alone does not establish exchanger suitability.

Source: DOCX P0413-P0461 and P0542-P0552.

$$
\overline\lambda_D=0.8511(200)(46.07)+(1-0.8511)(2314)(18.015),
$$

reported approximately as 14047 kJ/kmol. The source's ethanol latent-heat input 200 kJ/kg is not qualified here; it must not be adopted as a verified property.

$$
Q_C=\frac{122.599(14047)}{3600}\simeq478.378\ \mathrm{kW},\quad
\dot m_{cw}=\frac{478.378}{4.186(40-20)}\simeq5.714\ \mathrm{kg/s}.
$$

Initial sizing uses U=500 W/(m2 K), LMTD≈47.2 K, and selects 21.4 m2. The subsequent U=290 and LMTD=47.423 require

$$
A_{required}=\frac{1000(478.378)}{290(47.423)}=34.78437278\ldots\ \mathrm{m^2}>21.4\ \mathrm{m^2}.
$$

This is a replay of the report's own duty/coefficient inputs, not an independently rated condenser.

The source reports reboiler duty 120.568 kW after listing `Qw=122.764`, `QV=1.426`, `QR=3.43`, and `Qf=1.554` kW. Its displayed balance operands instead yield

Here the source's `QR` is its reflux heat term, distinct from the reboiler duty symbol `Q_R` used in this note.

$$
122.764+1.426-3.43-1.554=119.206\ \mathrm{kW}.
$$

The enthalpy bases and stream definitions in that calculation remain inconsistent. Neither 119.206 nor 120.568 is adopted as a validated new duty. Even the steam-use substitution differs:

$$
120.568/2181=0.0552810637\ldots\ \mathrm{kg/s},\quad 1.1(120.568/2181)=0.0608091701\ldots\ \mathrm{kg/s},
$$

versus the source's 0.0562/0.0613 kg/s. A full enthalpy calculation is required before utility or equipment selection.

### Pipe continuity and pump-head calculation

$$
d_{in}=\sqrt{\frac{4\dot V}{\pi u}},\qquad d_{in}=d_{OD}-2t,\qquad u_{actual}=\frac{4\dot V}{\pi d_{in}^2}.
$$

Use volumetric flow at the stream's local thermodynamic state. Outside diameter is not the flow diameter.

$$
H_{pump}=\frac{\Delta P}{\rho g}+\Delta z+\frac{\Delta(u^2)}{2g}+\sum h_f,\qquad P_{shaft}=\frac{\rho g\dot V H_{pump}}{\eta_{pump}}.
$$

A catalog pump must supply the required head at the required flow; neither a pipe diameter nor a motor rating proves that duty point.

$$
d_{in,required}=\sqrt{\frac{4(0.936)}{\pi(20)}}=0.2441057367\ldots\ \mathrm{m}.
$$

Source DOCX P0501-P0504 prints 24.41 mm and selects OD32×3 mm (ID26 mm). The formula with its own local vapor flow instead requires about **244.1 mm**; the factor-of-ten diameter error is retained as a finding.
