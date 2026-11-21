# case-1a: Worked calculations — Benzene/toluene distillation: 42 wt% benzene feed

Worked calculations reconstructed from the human engineer's preliminary design.

## 1. Notation and design basis

Component A is the more volatile component; B is the less volatile component. `F`, `D`, and `W` denote feed, distillate and bottoms molar flow in kmol/h. `B` in JSON stream tables is the same bottoms stream as `W` here. Mass fractions are `w`; mole fractions are `x`, with feed mole fraction `zF`. Use `d_c` for shell diameter, to distinguish it from distillate flow `D`.

| Input | Value | Unit / interpretation |
| --- | --- | --- |
| Components A / B | benzene / toluene | declared composition order |
| M_A / M_B | 78.11 / 92.13 | kg/kmol; source conversion constants |
| Annual throughput | 86500 | t/year of feed |
| Annual operation | 8000 | h/year |
| w_F / w_D | 0.42 / 0.997 | mass fraction |
| w_W | 0.003 | mass fraction |
| Top pressure | 106.325 | kPa absolute in controlled comparison |
| Feed condition | q=1 | saturated liquid |

Source requirement locations: PDF p. 7 (task); p. 8 (molar masses).

For gauge-pressure cases, 5 kPa + 101.325 kPa ambient = 106.325 kPa absolute; the reports generally round this to 106.3 kPa. Atmospheric ethanol/water is normalized to 101.325 kPa.

## 2. Mass-to-mole conversion and material balance

The following is **independent normalization of the original requirements**. It keeps full precision and does not silently substitute the reports' rounded mole fractions.

$$
x_A=\frac{w_A/M_A}{w_A/M_A+(1-w_A)/M_B},\qquad \overline M=x_AM_A+(1-x_A)M_B.
$$

$$
z_F=\frac{0.42/78.11}{0.42/78.11+(1-0.42)/92.13}=0.4606587745.
$$

$$
x_D=\frac{0.997/78.11}{0.997/78.11+(1-0.997)/92.13}=0.9974553671.
$$

$$
x_W=\frac{0.003/78.11}{0.003/78.11+(1-0.003)/92.13}=0.003536567.
$$

$$
\dot m_F=\frac{86500\times1000}{8000}=10812.5\ \mathrm{kg/h}.
$$

$$
F=\dot m_F\left(\frac{w_F}{M_A}+\frac{1-w_F}{M_B}\right)=10812.5\left(\frac{0.42}{78.11}+\frac{0.58}{92.13}\right)=126.2087383189\ \mathrm{kmol/h}.
$$

$$
F=D+W,\qquad Fz_F=Dx_D+Wx_W.
$$

$$
D=F\frac{z_F-x_W}{x_D-x_W},\qquad W=F-D,\qquad \eta_A=\frac{Dx_D}{Fz_F}.
$$

$$
D=126.20873832\frac{0.46065877-0.00353657}{0.99745537-0.00353657}=58.0458052\ \mathrm{kmol/h}.
$$

$$
W=68.16293312\ \mathrm{kmol/h},\qquad \eta_A=0.9958536936.
$$

| Quantity | Source-reported | Independent normalized result |
| --- | --- | --- |
| F (kmol/h) | 126.2087 | 126.2087383189 |
| D (kmol/h) | 58.0509 | 58.0458052007 |
| W (kmol/h) | 68.1578 | 68.1629331183 |
| z_F | 0.4607 | 0.4606587745 |
| x_D | 0.9975 | 0.9974553671 |
| x_W | 0.0035 | 0.003536567 |

Small differences can arise from intermediate rounding. Source arithmetic, labels and stage formulas must still be checked separately.

## 3. Human equilibrium model, minimum reflux and theoretical stages

This section retains the **human calculation approximation and its source-reported choices**. Replaying an approximate correlation is an arithmetic check, not experimental validation.

Source: PDF pp. 10-12. The report uses constant relative volatility

$$
\alpha=2.5,\qquad y^*(x)=\frac{\alpha x}{1+(\alpha-1)x},\qquad x=\frac{y}{\alpha-(\alpha-1)y}.
$$

For a feed pinch with saturated-liquid feed, `q=1`, the q-line is vertical:

$$
x=z_F,\qquad y_F^*=\frac{2.5\times0.4607}{1+(2.5-1)\times0.4607}=0.681085716.
$$

$$
R_{\min,\alpha}=\frac{x_D-y_F^*}{y_F^*-z_F}=1.4357295464.
$$

The source reports Rmin=1.99 and chooses R=3.98.

The report instead substitutes an Aspen-read `y_e=0.64` and `zF=0.4607`, while describing the read point as `x_e=0.42`. These are distinct composition bases.

$$
\frac{0.9975-0.64}{0.64-0.4607}=1.993865\ldots
$$

The result near 1.99 is reproducible from those operands, but differs from the minimum reflux of its own constant-alpha curve. Neither value is silently replaced in the human design.

### Operating lines and internal loads

For constant molar overflow and saturated-liquid feed:

$$
L=RD,\quad V=(R+1)D,\quad L_s=L+qF,\quad V_s=V+(q-1)F=V.
$$

$$
L=3.98\times58.0509=231.042582;\quad V=(3.98+1)\times58.0509=289.093482\quad[\mathrm{kmol/h}].
$$

$$
L_s=231.042582+126.2087=357.251282,\qquad V_s=289.093482\quad[\mathrm{kmol/h}].
$$

These are recomputed from the displayed human R/D/F, not copied rounded internal loads.

$$
y_R(x)=\frac{R}{R+1}x+\frac{x_D}{R+1},\qquad y_S(x)=\frac{L_s}{V_s}x-\frac{W}{V_s}x_W.
$$

$$
y_R(x)=0.7991967871x+0.2003012048.
$$

With a closed split, the stripping line also follows from the feed intersection:

$$
y_q=y_R(z_F),\qquad m_S=\frac{y_q-x_W}{z_F-x_W},\qquad y_S(x)=x_W+m_S(x-x_W).
$$

This intersection form avoids a small discontinuity caused solely by independently rounded source F/D/W. Starting at `y1=xD`, find `x_n` from the equilibrium relation, then set `y_(n+1)=y_R(x_n)` above the feed or `y_S(x_n)` below it. Stop when `x_n<=xW`. The first crossing of `zF` identifies the feed stage in this reconstruction.

### Independently reconstructed constant-alpha stage table

These rows replay the source approximation from its rounded zF/xD/xW/R; they are **not a transcription of every source graph point** and are not the Agent's property model.

| Stage | y entering equilibrium step | x from inverse equilibrium | Operating-line section |
| --- | --- | --- | --- |
| 1 | 0.9975 | 0.99377335 | rectifying |
| 2 | 0.994521673 | 0.986415811 | rectifying |
| 3 | 0.988641552 | 0.972079578 | rectifying |
| 4 | 0.977184081 | 0.944847727 | rectifying |
| 5 | 0.955420472 | 0.895536576 | rectifying |
| 6 | 0.916011159 | 0.813521116 | rectifying |
| 7 | 0.850464667 | 0.694652114 | rectifying |
| 8 | 0.755464943 | 0.552724256 | rectifying |
| 9 | 0.642036654 | 0.417735603 | stripping |
| 10 | 0.515397323 | 0.298451632 | stripping |
| 11 | 0.367990521 | 0.18890546 | stripping |
| 12 | 0.232617337 | 0.108140091 | stripping |
| 13 | 0.132810426 | 0.057723978 | stripping |
| 14 | 0.070508024 | 0.029449046 | stripping |
| 15 | 0.035566889 | 0.014536977 | stripping |
| 16 | 0.017139095 | 0.00692687 | stripping |
| 17 | 0.007734802 | 0.003108346 | stripping |

The replay reaches the rounded bottoms target after 17 equilibrium steps, with feed stage 9. The report states N=17, feed stage 9.

Stage convention for comparison: include the partial reboiler and exclude the total condenser. An integer step count is not a physical tray count.

## 4. Human tray-efficiency, pressure and height calculations

The source applies an OConnell-type empirical correlation. In its reported convention, viscosity is inserted numerically in mPa·s (cP), and efficiency is a fraction:

$$
E_O=0.49(\alpha\mu_L)^{-0.245},\qquad N_{\mathrm{actual},s}=\left\lceil\frac{N_{\mathrm{theoretical},s}}{E_{O,s}}\right\rceil.
$$

This reproduces the source's empirical method only. Its applicability and the underlying viscosity/volatility values are not independently qualified here. Global OConnell efficiency is not stagewise Murphree efficiency.

Source: PDF pp. 11-13, 21.

$$
E_O=0.49(2.35\times0.2726)^{-0.245}\simeq0.55.
$$

$$
N_{p,R}=\lceil8/0.55\rceil=15,\quad N_{p,S}=\lceil9/0.55\rceil=17,\quad N_p=32.
$$

The theoretical 17 includes the reboiler, so the source's section-to-physical-tray counting needs review.

$$
Z_R=(15-1)0.45=6.3\ \mathrm{m},\quad Z_S=(17-1)0.45=7.2\ \mathrm{m},
$$

$$
Z=6.3+7.2+0.8=14.3\ \mathrm{m}.
$$

This is reported active height, not total vessel height. Source top/bottom pressures are 106.3/128 kPa; the assumed physical-tray drop is 0.7 kPa. The controlled theoretical-stage simulation instead holds top pressure constant.

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

Source locations: PDF pp. 18-24, 27-28, 32-36. The following representative rectifying-section substitution uses displayed source inputs:

$$
u_f=0.0808\sqrt{\frac{813.0858-2.9692}{2.9692}}=1.33464388\ \mathrm{m/s},\qquad u=0.7u_f=0.93425072\ \mathrm{m/s}.
$$

$$
d_{c,\mathrm{calc}}=\sqrt{\frac{4(2.1135)}{\pi(0.93425072)}}=1.69716656\ \mathrm{m}.
$$

The source selects shell diameter **1.8 m** after its section checks. The calculation just shown is a replay of one section, not a new independent shell rating.

### Weir and downcomer

$$
l_w=f_wd_c,\quad h_{ow}=\frac{2.84}{1000}E\left(\frac{3600\dot L}{l_w}\right)^{2/3},\quad h_w=h_L-h_{ow}.
$$

$$
l_w=0.65\times1.8=1.17\ \mathrm{m},\qquad h_{ow}(E=1)=0.02027639\ \mathrm{m}.
$$

The replay sets E=1 for the displayed comparison. The ethanol source instead selects E=1.02 and rounds the liquid head to 10 mm; these choices must not be interchanged silently.

$$
A_f=f_AA_T,\qquad \theta=\frac{A_fH_T}{\dot L},\qquad u_d=\frac{\dot L}{A_f}.
$$

$$
A_T=\frac{\pi(1.8)^2}{4}=2.54469005\ \mathrm{m^2},\quad A_f=0.07A_T=0.1781283\ \mathrm{m^2},\quad \theta=\frac{0.1781283(0.45)}{0.0062}=12.92866719\ \mathrm{s}.
$$

The normalized rounded shell area above can differ from a source area carried forward before rounding. Residence time checks only the stated geometry/flow arithmetic, not downcomer operability.

$$
h_0=\frac{\dot L}{l_wu_{dc}}\quad\text{or the source-selected rule }h_0=h_w-0.006\ \mathrm{m}.
$$

### Valve layout and hydraulic operating window

$$
F_0=u_0\sqrt{\rho_V},\qquad N_v=\frac{\dot V}{(\pi d_0^2/4)u_0},\qquad \phi=\frac{N_v\pi d_0^2/4}{A_T}.
$$

The source uses valve-hole diameter `d0=0.039 m` and nominal hole factor `F0=10`. Its estimated valve count for the representative section is 305. The empirical F0 unit is `(m/s) sqrt(kg/m3)`; it is not a dimensionless friction factor.

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

**Source inconsistency:** PDF p. 20 calculates a fourth-section diameter near 1.9001 m (rounded in the report to 1.9 m), then adopts 1.8 m. The maximum-section selection needs review. Later operating-window formulas also use 140 holes and densities different from the preceding section design; the source summary alone does not resolve that change.

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

The extracted report covers process selection, balance, stages, shell/trays, hydraulic checks and a summary (PDF pp. 8-36). It does **not provide a separately established condenser/reboiler duty and exchanger-area calculation in those chapters**. Consequently no source duty, heat-transfer coefficient or exchanger area is invented here. External DWSIM duties are reported in Section 8.

### Pipe continuity and pump-head calculation

$$
d_{in}=\sqrt{\frac{4\dot V}{\pi u}},\qquad d_{in}=d_{OD}-2t,\qquad u_{actual}=\frac{4\dot V}{\pi d_{in}^2}.
$$

Use volumetric flow at the stream's local thermodynamic state. Outside diameter is not the flow diameter.

$$
H_{pump}=\frac{\Delta P}{\rho g}+\Delta z+\frac{\Delta(u^2)}{2g}+\sum h_f,\qquad P_{shaft}=\frac{\rho g\dot V H_{pump}}{\eta_{pump}}.
$$

A catalog pump must supply the required head at the required flow; neither a pipe diameter nor a motor rating proves that duty point.
