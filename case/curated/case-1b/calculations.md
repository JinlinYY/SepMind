# case-1b: Worked calculations — Benzene/toluene distillation: 36 wt% benzene feed

Worked calculations reconstructed from the human engineer's preliminary design.

## 1. Notation and design basis

Component A is the more volatile component; B is the less volatile component. `F`, `D`, and `W` denote feed, distillate and bottoms molar flow in kmol/h. `B` in JSON stream tables is the same bottoms stream as `W` here. Mass fractions are `w`; mole fractions are `x`, with feed mole fraction `zF`. Use `d_c` for shell diameter, to distinguish it from distillate flow `D`.

| Input | Value | Unit / interpretation |
| --- | --- | --- |
| Components A / B | benzene / toluene | declared composition order |
| M_A / M_B | 78.0 / 92.0 | kg/kmol; source conversion constants |
| Annual throughput | 95500 | t/year of feed |
| Annual operation | 8000 | h/year |
| w_F / w_D | 0.36 / 0.997 | mass fraction |
| Recovery requirement | 0.997 | component molar recovery |
| Top pressure | 106.325 | kPa absolute in controlled comparison |
| Feed condition | q=1 | saturated liquid |

Source requirement locations: DOCX P0108, P0122-P0134; recovery P0128; later gauge pressure P0311.

For gauge-pressure cases, 5 kPa + 101.325 kPa ambient = 106.325 kPa absolute; the reports generally round this to 106.3 kPa. Atmospheric ethanol/water is normalized to 101.325 kPa.

## 2. Mass-to-mole conversion and material balance

The following is **independent normalization of the original requirements**. It keeps full precision and does not silently substitute the reports' rounded mole fractions.

```math
x_A=\frac{w_A/M_A}{w_A/M_A+(1-w_A)/M_B},\qquad \overline M=x_AM_A+(1-x_A)M_B.
```

```math
z_F=\frac{0.36/78.0}{0.36/78.0+(1-0.36)/92.0}=0.3988439306.
```

```math
x_D=\frac{0.997/78.0}{0.997/78.0+(1-0.997)/92.0}=0.9974553601.
```

```math
\dot m_F=\frac{95500\times1000}{8000}=11937.5\ \mathrm{kg/h}.
```

```math
F=\dot m_F\left(\frac{w_F}{M_A}+\frac{1-w_F}{M_B}\right)=11937.5\left(\frac{0.36}{78.0}+\frac{0.64}{92.0}\right)=138.139632107\ \mathrm{kmol/h}.
```

```math
F=D+W,\qquad Fz_F=Dx_D+Wx_W.
```

```math
\eta_A=\frac{Dx_D}{Fz_F},\qquad D=\frac{Fz_F\eta_A}{x_D},\quad W=F-D,\quad x_W=\frac{Fz_F-Dx_D}{W}.
```

```math
D=\frac{138.13963211\times0.39884393\times0.997}{0.99745536}=55.07100125\ \mathrm{kmol/h}.
```

The bottoms composition is an output in this case; it was not leaked to the Agent as a second product target.

```math
W=83.06863085\ \mathrm{kmol/h},\qquad \eta_A=0.997.
```

| Quantity | Source-reported | Independent normalized result |
| --- | --- | --- |
| F (kmol/h) | 138.13 | 138.139632107 |
| D (kmol/h) | 55.06 | 55.0710012542 |
| W (kmol/h) | 83.07 | 83.0686308528 |
| z_F | 0.3988 | 0.3988439306 |
| x_D | 0.9975 | 0.9974553601 |
| x_W | 0.002 | 0.0019897819 |

Small differences can arise from intermediate rounding. Source arithmetic, labels and stage formulas must still be checked separately.

## 3. Human equilibrium model, minimum reflux and theoretical stages

This section retains the **human calculation approximation and its source-reported choices**. Replaying an approximate correlation is an arithmetic check, not experimental validation.

Source: DOCX P0260-P0310. The report uses constant relative volatility

```math
\alpha=2.45,\qquad y^{\ast}(x)=\frac{\alpha x}{1+(\alpha-1)x},\qquad x=\frac{y}{\alpha-(\alpha-1)y}.
```

For a feed pinch with saturated-liquid feed, `q=1`, the q-line is vertical:

```math
x=z_F,\qquad y_F^{\ast}=\frac{2.45\times0.3988}{1+(2.45-1)\times0.3988}=0.6190741703.
```

```math
R_{\min,\alpha}=\frac{x_D-y_F^{\ast}}{y_F^{\ast}-z_F}=1.7179764165.
```

The source reports Rmin=1.719 and chooses R=2.75.

### Operating lines and internal loads

For constant molar overflow and saturated-liquid feed:

```math
L=RD,\quad V=(R+1)D,\quad L_s=L+qF,\quad V_s=V+(q-1)F=V.
```

```math
L=2.75\times55.06=151.415;\quad V=(2.75+1)\times55.06=206.475\quad[\mathrm{kmol/h}].
```

```math
L_s=151.415+138.13=289.545,\qquad V_s=206.475\quad[\mathrm{kmol/h}].
```

These are recomputed from the displayed human R/D/F, not copied rounded internal loads.

```math
y_R(x)=\frac{R}{R+1}x+\frac{x_D}{R+1},\qquad y_S(x)=\frac{L_s}{V_s}x-\frac{W}{V_s}x_W.
```

```math
y_R(x)=0.7333333333x+0.266.
```

With a closed split, the stripping line also follows from the feed intersection:

```math
y_q=y_R(z_F),\qquad m_S=\frac{y_q-x_W}{z_F-x_W},\qquad y_S(x)=x_W+m_S(x-x_W).
```

This intersection form avoids a small discontinuity caused solely by independently rounded source F/D/W. Starting at `y1=xD`, find `x_n` from the equilibrium relation, then set `y_(n+1)=y_R(x_n)` above the feed or `y_S(x_n)` below it. Stop when `x_n<=xW`. The first crossing of `zF` identifies the feed stage in this reconstruction.

### Independently reconstructed constant-alpha stage table

These rows replay the source approximation from its rounded zF/xD/xW/R; they are **not a transcription of every source graph point** and are not the Agent's property model.

| Stage | y entering equilibrium step | x from inverse equilibrium | Operating-line section |
| --- | --- | --- | --- |
| 1 | 0.9975 | 0.993897123 | rectifying |
| 2 | 0.99485789 | 0.987495068 | rectifying |
| 3 | 0.99016305 | 0.976238398 | rectifying |
| 4 | 0.981908159 | 0.956808051 | rectifying |
| 5 | 0.967659237 | 0.924314342 | rectifying |
| 6 | 0.943830518 | 0.872748835 | rectifying |
| 7 | 0.906015812 | 0.797354654 | rectifying |
| 8 | 0.850726747 | 0.69935418 | rectifying |
| 9 | 0.778859732 | 0.589753328 | rectifying |
| 10 | 0.698485774 | 0.486006053 | rectifying |
| 11 | 0.622404439 | 0.402196435 | rectifying |
| 12 | 0.560944052 | 0.342743117 | stripping |
| 13 | 0.479841843 | 0.273534272 | stripping |
| 14 | 0.382786671 | 0.202002579 | stripping |
| 15 | 0.282474046 | 0.138439667 | stripping |
| 16 | 0.193336461 | 0.089109018 | stripping |
| 17 | 0.124157518 | 0.054695626 | stripping |
| 18 | 0.075897825 | 0.032435687 | stripping |
| 19 | 0.04468155 | 0.01873274 | stripping |
| 20 | 0.025465193 | 0.010553003 | stripping |
| 21 | 0.013994322 | 0.005759672 | stripping |
| 22 | 0.007272384 | 0.002981151 | stripping |
| 23 | 0.003375919 | 0.001380685 | stripping |

The replay reaches the rounded bottoms target after 23 equilibrium steps, with feed stage 12. The report states N=23, feed stage 12.

Stage convention for comparison: include the partial reboiler and exclude the total condenser. An integer step count is not a physical tray count.

## 4. Human tray-efficiency, pressure and height calculations

The source applies an OConnell-type empirical correlation. In its reported convention, viscosity is inserted numerically in mPa·s (cP), and efficiency is a fraction:

```math
E_O=0.49(\alpha\mu_L)^{-0.245},\qquad N_{\mathrm{actual},s}=\left\lceil\frac{N_{\mathrm{theoretical},s}}{E_{O,s}}\right\rceil.
```

This reproduces the source's empirical method only. Its applicability and the underlying viscosity/volatility values are not independently qualified here. Global OConnell efficiency is not stagewise Murphree efficiency.

Source: DOCX P0299-P0325, P0502-P0508, P1090-P1103.

```math
E_R=0.49(2.55\times0.289)^{-0.245}\simeq0.528,\quad E_S=0.49(2.35\times0.26)^{-0.245}\simeq0.5529.
```

```math
N_{p,R}=\lceil11/0.528\rceil=21,\quad N_{p,S}=\lceil11/0.5529\rceil=20,\quad N_p=21+20+1=42.
```

The report places the actual feed tray at 22 and gives `(23-1)/42≈52%` overall efficiency. Its added feed/reboiler counting is retained as reported.

```math
P_D=106.3,\quad P_F=106.3+22(0.7)=121.7,\quad P_W=106.3+42(0.7)=135.7\quad[\mathrm{kPa}].
```

```math
Z=(21-1)0.45+(20-1)0.45+0.8=18.35\ \mathrm{m}.
```

```math
H=(42-2-4)0.45+0.425+4(0.650)+0.8+1.8+2.57+3=27.395\ \mathrm{m}.
```

The last expression includes source-selected head/manhole/feed/end spaces and skirt allowance. It is a source geometry reconstruction, not an equipment approval.

## 5. Human shell diameter, tray geometry and hydraulic checks

The source uses chart-derived capacity factors and source-reported transport properties. The formulas below explain that calculation path; chart readings, material properties and empirical bounds remain unverified source inputs.

```math
\dot V=\frac{V\overline M_V}{3600\rho_V},\qquad \dot L=\frac{L\overline M_L}{3600\rho_L}\quad[\mathrm{m^3/s}].
```

```math
F_{LV}=\frac{\dot L}{\dot V}\sqrt{\frac{\rho_L}{\rho_V}},\quad C=C_{20}\left(\frac{\sigma}{20}\right)^{0.2},\quad u_f=C\sqrt{\frac{\rho_L-\rho_V}{\rho_V}}.
```

Here the empirical surface-tension correction uses sigma numerically in mN/m and the reference 20 mN/m. The allowable velocity `u=k u_f` uses the source-selected capacity fraction `k`.

```math
d_c=\sqrt{\frac{4\dot V}{\pi u}},\qquad A_T=\frac{\pi d_c^2}{4},\qquad u_{\mathrm{actual}}=\frac{\dot V}{A_T}.
```

Source locations: DOCX P0455-P0568, P0630-P0692. The following representative rectifying-section substitution uses displayed source inputs:

```math
u_f=0.0865\sqrt{\frac{805.634-2.72}{2.72}}=1.48616206\ \mathrm{m/s},\qquad u=0.7u_f=1.04031344\ \mathrm{m/s}.
```

```math
d_{c,\mathrm{calc}}=\sqrt{\frac{4(1.691864)}{\pi(1.04031344)}}=1.43898305\ \mathrm{m}.
```

The source selects shell diameter **1.6 m** after its section checks. The calculation just shown is a replay of one section, not a new independent shell rating.

### Weir and downcomer

```math
l_w=f_wd_c,\quad h_{ow}=\frac{2.84}{1000}E\left(\frac{3600\dot L}{l_w}\right)^{2/3},\quad h_w=h_L-h_{ow}.
```

```math
l_w=0.6\times1.6=0.96\ \mathrm{m},\qquad h_{ow}(E=1)=0.01815477\ \mathrm{m}.
```

The replay sets E=1 for the displayed comparison. The ethanol source instead selects E=1.02 and rounds the liquid head to 10 mm; these choices must not be interchanged silently.

```math
A_f=f_AA_T,\qquad \theta=\frac{A_fH_T}{\dot L},\qquad u_d=\frac{\dot L}{A_f}.
```

```math
A_T=\frac{\pi(1.6)^2}{4}=2.0106193\ \mathrm{m^2},\quad A_f=0.055A_T=0.11058406\ \mathrm{m^2},\quad \theta=\frac{0.11058406(0.45)}{0.00431}=11.54589968\ \mathrm{s}.
```

The normalized rounded shell area above can differ from a source area carried forward before rounding. Residence time checks only the stated geometry/flow arithmetic, not downcomer operability.

```math
h_0=\frac{\dot L}{l_wu_{dc}}\quad\text{or the source-selected rule }h_0=h_w-0.006\ \mathrm{m}.
```

### Valve layout and hydraulic operating window

```math
F_0=u_0\sqrt{\rho_V},\qquad N_v=\frac{\dot V}{(\pi d_0^2/4)u_0},\qquad \phi=\frac{N_v\pi d_0^2/4}{A_T}.
```

The source uses valve-hole diameter `d0=0.039 m` and nominal hole factor `F0=8`. Its estimated valve count for the representative section is 292. The empirical F0 unit is `(m/s) sqrt(kg/m3)`; it is not a dimensionless friction factor.

```math
h_c=\xi\frac{\rho_Vu_0^2}{2g\rho_L},\qquad h_p=h_c+\beta h_L+h_\sigma,\qquad h_d=0.153\left(\frac{\dot L}{l_wh_0}\right)^2.
```

```math
H_{dc}=h_p+h_d+h_L<\varphi(H_T+h_w).
```

These liquid-head expressions require all lengths in m. The source uses valve-specific dry-pressure-drop coefficients near 5.34-5.37 for the stated regime and an aeration factor near 0.5. They must not be applied outside that regime without supporting data.

```math
\dot L_{\max}=\frac{A_fH_T}{\theta_{\min}},\qquad \dot L_{\min}=\frac{l_w}{3600}\left(\frac{1000h_{ow,\min}}{2.84E}\right)^{3/2}.
```

The source constructs the operating window from minimum weir head, downcomer residence time, minimum valve-hole factor, entrainment and downcomer flooding. A standard transcription of its entrainment index is

```math
f_{\mathrm{ent}}=\frac{\dot V\sqrt{\rho_V/(\rho_L-\rho_V)}+1.36\dot L Z_L}{K_FC_FA_b}.
```

The chart factor CF, path length ZL, bubbling area Ab and property correction KF must refer to the same section. This note does not certify a flooding/entrainment margin from the source's graphs.

## 6. Human condenser, reboiler, utilities and nozzles

For source latent heats in kJ/kg and molar masses in kg/kmol, the mixture molar latent heat is in **kJ/kmol**, not kJ/mol:

```math
\overline\lambda=\sum_i x_iM_i\lambda_i,\qquad Q_{\mathrm{lat}}=\frac{\dot n\overline\lambda}{3600}\quad[\mathrm{kW}].
```

This latent-only estimate is not a complete enthalpy balance and does not verify the latent-heat source or temperature range. For the entire column, with condenser heat removed and reboiler heat supplied taken positive:

```math
\frac{Fh_F}{3600}+Q_R=\frac{Dh_D+Wh_W}{3600}+Q_C.
```

Here F/D/W are in kmol/h, h is in kJ/kmol, and Q is in kW; the factors of 3600 keep all terms on the same basis.

```math
\dot m_{cw}=\frac{Q_C}{c_{p,cw}(T_{cw,out}-T_{cw,in})},\qquad \dot m_{steam}=\frac{Q_R}{\lambda_{steam}}.
```

```math
\Delta T_{lm}=\frac{\Delta T_1-\Delta T_2}{\ln(\Delta T_1/\Delta T_2)},\qquad A=\frac{1000Q}{U\Delta T_{lm}}.
```

Here Q is kW, U is W/(m2 K), and A is m2. A chosen fouling or heat-loss allowance must be recorded explicitly; a larger catalog area alone does not establish exchanger suitability.

Source: DOCX P0891-P0949. The displayed condenser calculation is

```math
\overline\lambda_D=0.9975(383.9264)(78)+(1-0.9975)(371.2807)(92)\simeq29956.788\ \mathrm{kJ/kmol},
```

```math
Q_C=\frac{206.475(29956.788)}{3600}\simeq1718.15\ \mathrm{kW}.
```

```math
\dot m_{cw}=\frac{1718.15}{4.186(35-20)}\simeq27.36\ \mathrm{kg/s},\quad
A_C=\frac{1000(1718.15)}{800(52.2)}\simeq41.14\ \mathrm{m^2}.
```

The report selects a condenser area of 43.5 m2. For its reboiler:

```math
Q_R=\frac{206.475(34243.932)}{3600}\simeq1964.03\ \mathrm{kW},\quad
\Delta T=127.44-110.43=17.01\ \mathrm{K},
```

```math
A_R=\frac{1000(1964.03)}{1000(17.01)}\simeq115.46\ \mathrm{m^2},\quad
A_{R,allow}=1.1A_R\simeq127.006\ \mathrm{m^2}.
```

Selected reboiler area is 133.9 m2. Steam use with the stated 10% allowance is `1.1×1964.03/2181≈0.991 kg/s`. The source states 0.25 MPa gauge steam and 127.44 C; this pressure/temperature pairing is retained as an unverified source claim, not a verified saturation-state pair.

Source feed-pump arithmetic (P0952-P0980): `Qv=0.004159 m3/s=14.9724 m3/h`; the selected pump table gives 3.75 m3/h. This capacity mismatch remains unresolved.

### Pipe continuity and pump-head calculation

```math
d_{in}=\sqrt{\frac{4\dot V}{\pi u}},\qquad d_{in}=d_{OD}-2t,\qquad u_{actual}=\frac{4\dot V}{\pi d_{in}^2}.
```

Use volumetric flow at the stream's local thermodynamic state. Outside diameter is not the flow diameter.

```math
H_{pump}=\frac{\Delta P}{\rho g}+\Delta z+\frac{\Delta(u^2)}{2g}+\sum h_f,\qquad P_{shaft}=\frac{\rho g\dot V H_{pump}}{\eta_{pump}}.
```

A catalog pump must supply the required head at the required flow; neither a pipe diameter nor a motor rating proves that duty point.
