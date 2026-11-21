# case-3: Worked calculations — Methanol/water distillation: methanol product throughput specified

Worked calculations reconstructed from the human engineer's preliminary design.

## 1. Notation and design basis

Component A is the more volatile component; B is the less volatile component. `F`, `D`, and `W` denote feed, distillate and bottoms molar flow in kmol/h. `B` in JSON stream tables is the same bottoms stream as `W` here. Mass fractions are `w`; mole fractions are `x`, with feed mole fraction `zF`. Use `d_c` for shell diameter, to distinguish it from distillate flow `D`.

| Input | Value | Unit / interpretation |
| --- | --- | --- |
| Components A / B | methanol / water | declared composition order |
| M_A / M_B | 32.0 / 18.0 | kg/kmol; source conversion constants |
| Annual throughput | 32580 | t/year of distillate product |
| Annual operation | 8000 | h/year |
| w_F / w_D | 0.4 / 0.995 | mass fraction |
| w_W | 0.0005 | mass fraction |
| Top pressure | 106.325 | kPa absolute in controlled comparison |
| Feed condition | q=1 | saturated liquid |

Source requirement locations: PDF p. 2 (product throughput and requirements), p. 9 (molar masses); p. 19 (gauge pressure).

For gauge-pressure cases, 5 kPa + 101.325 kPa ambient = 106.325 kPa absolute; the reports generally round this to 106.3 kPa. Atmospheric ethanol/water is normalized to 101.325 kPa.

## 2. Mass-to-mole conversion and material balance

The following is **independent normalization of the original requirements**. It keeps full precision and does not silently substitute the reports' rounded mole fractions.

$$
x_A=\frac{w_A/M_A}{w_A/M_A+(1-w_A)/M_B},\qquad \overline M=x_AM_A+(1-x_A)M_B.
$$

$$
z_F=\frac{0.4/32.0}{0.4/32.0+(1-0.4)/18.0}=0.2727272727.
$$

$$
x_D=\frac{0.995/32.0}{0.995/32.0+(1-0.995)/18.0}=0.9911455451.
$$

$$
x_W=\frac{0.0005/32.0}{0.0005/32.0+(1-0.0005)/18.0}=0.0002813115.
$$

Here the stated capacity is **distillate product**, not feed.

$$
\dot m_D=\frac{32580\times1000}{8000}=4072.5\ \mathrm{kg/h}.
$$

$$
\dot m_F=\dot m_D\frac{w_D-w_W}{w_F-w_W}
$$

$$
\dot m_F=4072.5\frac{0.995-0.0005}{0.4-0.0005}=10137.92553191\ \mathrm{kg/h}.
$$

$$
F=\dot m_F\left(\frac{w_F}{M_A}+\frac{1-w_F}{M_B}\right)=10137.92553191\left(\frac{0.4}{32.0}+\frac{0.6}{18.0}\right)=464.6549202128\ \mathrm{kmol/h}.
$$

$$
F=D+W,\qquad Fz_F=Dx_D+Wx_W.
$$

$$
D=F\frac{z_F-x_W}{x_D-x_W},\qquad W=F-D,\qquad \eta_A=\frac{Dx_D}{Fz_F}.
$$

$$
D=464.65492021\frac{0.27272727-0.00028131}{0.99114555-0.00028131}=127.76054687\ \mathrm{kmol/h}.
$$

$$
W=336.89437334\ \mathrm{kmol/h},\qquad \eta_A=0.9992521368.
$$

| Quantity | Source-reported | Independent normalized result |
| --- | --- | --- |
| F (kmol/h) | 464.63 | 464.6549202128 |
| D (kmol/h) | 127.74 | 127.760546875 |
| W (kmol/h) | 336.89 | 336.8943733378 |
| z_F | 0.2727 | 0.2727272727 |
| x_D | 0.9911 | 0.9911455451 |
| x_W | 0.0003 | 0.0002813115 |

Small differences can arise from intermediate rounding. Source arithmetic, labels and stage formulas must still be checked separately.

## 3. Human equilibrium model, minimum reflux and theoretical stages

This section retains the **human calculation approximation and its source-reported choices**. Replaying an approximate correlation is an arithmetic check, not experimental validation.

Source: PDF pp. 17-19. The report uses constant relative volatility

$$
\alpha=4.94,\qquad y^*(x)=\frac{\alpha x}{1+(\alpha-1)x},\qquad x=\frac{y}{\alpha-(\alpha-1)y}.
$$

For a feed pinch with saturated-liquid feed, `q=1`, the q-line is vertical:

$$
x=z_F,\qquad y_F^*=\frac{4.94\times0.2727}{1+(4.94-1)\times0.2727}=0.649399018.
$$

$$
R_{\min,\alpha}=\frac{x_D-y_F^*}{y_F^*-z_F}=0.9070928401.
$$

The source reports Rmin=0.909 and chooses R=1.454.

The task requires `R/Rmin=1.6`. Its human implementation uses rounded values `1.6×0.909≈1.454`. The Agent separately computes Rmin and honors the same multiplier.

### Operating lines and internal loads

For constant molar overflow and saturated-liquid feed:

$$
L=RD,\quad V=(R+1)D,\quad L_s=L+qF,\quad V_s=V+(q-1)F=V.
$$

$$
L=1.454\times127.74=185.73396;\quad V=(1.454+1)\times127.74=313.47396\quad[\mathrm{kmol/h}].
$$

$$
L_s=185.73396+464.63=650.36396,\qquad V_s=313.47396\quad[\mathrm{kmol/h}].
$$

These are recomputed from the displayed human R/D/F, not copied rounded internal loads.

$$
y_R(x)=\frac{R}{R+1}x+\frac{x_D}{R+1},\qquad y_S(x)=\frac{L_s}{V_s}x-\frac{W}{V_s}x_W.
$$

$$
y_R(x)=0.5925020375x+0.4038712306.
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
| 1 | 0.9911 | 0.957523482 | rectifying |
| 2 | 0.971205844 | 0.87224998 | rectifying |
| 3 | 0.920681121 | 0.701462574 | rectifying |
| 4 | 0.819489235 | 0.478893929 | rectifying |
| 5 | 0.687616859 | 0.308239229 | rectifying |
| 6 | 0.586503602 | 0.223075079 | stripping |
| 7 | 0.462490031 | 0.148339092 | stripping |
| 8 | 0.307435757 | 0.082451122 | stripping |
| 9 | 0.170738408 | 0.040010963 | stripping |
| 10 | 0.08268808 | 0.017920315 | stripping |
| 11 | 0.036856756 | 0.007686843 | stripping |
| 12 | 0.015625436 | 0.00320296 | stripping |
| 13 | 0.006322753 | 0.001286397 | stripping |
| 14 | 0.002346471 | 0.000475885 | stripping |
| 15 | 0.000664907 | 0.000134668 | stripping |

The replay reaches the rounded bottoms target after 15 equilibrium steps, with feed stage 6. The report states N=15, feed stage 6.

Stage convention for comparison: include the partial reboiler and exclude the total condenser. An integer step count is not a physical tray count.

## 4. Human tray-efficiency, pressure and height calculations

The source applies an OConnell-type empirical correlation. In its reported convention, viscosity is inserted numerically in mPa·s (cP), and efficiency is a fraction:

$$
E_O=0.49(\alpha\mu_L)^{-0.245},\qquad N_{\mathrm{actual},s}=\left\lceil\frac{N_{\mathrm{theoretical},s}}{E_{O,s}}\right\rceil.
$$

This reproduces the source's empirical method only. Its applicability and the underlying viscosity/volatility values are not independently qualified here. Global OConnell efficiency is not stagewise Murphree efficiency.

Source: PDF pp. 19-20, 26, 54-55.

$$
E_R=0.49(3.25\times0.344)^{-0.245}\simeq0.4768,\quad E_S=0.49(6.62\times0.314)^{-0.245}\simeq0.4096.
$$

$$
N_{p,R}=\lceil5/0.4768\rceil=11,\quad N_{p,S}=\lceil9/0.4096\rceil=22,\quad N_p=11+22+1=34.
$$

The source reports actual feed tray 12 and overall efficiency `(15-1)/34≈41%`.

$$
P_D=106.3,\quad P_F=106.3+12(0.7)=114.7,\quad P_W=106.3+34(0.7)=130.1\quad[\mathrm{kPa}].
$$

$$
Z=(11-1)0.45+(22-1)0.45+0.8=14.75\ \mathrm{m}.
$$

$$
H=(34-2-3)0.45+0.375+3(0.650)+0.8+1.8+1.97+3=22.945\ \mathrm{m}.
$$

The physical-tray pressure profile is separate from the constant-pressure theoretical-stage comparison. No stagewise efficiency model is inferred from the global efficiency.

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

Source locations: PDF pp. 23-31. The following representative rectifying-section substitution uses displayed source inputs:

$$
u_f=0.0931\sqrt{\frac{803.6-1.04}{1.04}}=2.58625752\ \mathrm{m/s},\qquad u=0.7u_f=1.81038026\ \mathrm{m/s}.
$$

$$
d_{c,\mathrm{calc}}=\sqrt{\frac{4(2.457137)}{\pi(1.81038026)}}=1.3145734\ \mathrm{m}.
$$

The source selects shell diameter **1.4 m** after its section checks. The calculation just shown is a replay of one section, not a new independent shell rating.

### Weir and downcomer

$$
l_w=f_wd_c,\quad h_{ow}=\frac{2.84}{1000}E\left(\frac{3600\dot L}{l_w}\right)^{2/3},\quad h_w=h_L-h_{ow}.
$$

$$
l_w=0.6\times1.4=0.84\ \mathrm{m},\qquad h_{ow}(E=1)=0.01053475\ \mathrm{m}.
$$

The replay sets E=1 for the displayed comparison. The ethanol source instead selects E=1.02 and rounds the liquid head to 10 mm; these choices must not be interchanged silently.

$$
A_f=f_AA_T,\qquad \theta=\frac{A_fH_T}{\dot L},\qquad u_d=\frac{\dot L}{A_f}.
$$

$$
A_T=\frac{\pi(1.4)^2}{4}=1.5393804\ \mathrm{m^2},\quad A_f=0.055A_T=0.08466592\ \mathrm{m^2},\quad \theta=\frac{0.08466592(0.45)}{0.001667}=22.8552279\ \mathrm{s}.
$$

The normalized rounded shell area above can differ from a source area carried forward before rounding. Residence time checks only the stated geometry/flow arithmetic, not downcomer operability.

$$
h_0=\frac{\dot L}{l_wu_{dc}}\quad\text{or the source-selected rule }h_0=h_w-0.006\ \mathrm{m}.
$$

### Valve layout and hydraulic operating window

$$
F_0=u_0\sqrt{\rho_V},\qquad N_v=\frac{\dot V}{(\pi d_0^2/4)u_0},\qquad \phi=\frac{N_v\pi d_0^2/4}{A_T}.
$$

The source uses valve-hole diameter `d0=0.039 m` and nominal hole factor `F0=8`. Its estimated valve count for the representative section is 262. The empirical F0 unit is `(m/s) sqrt(kg/m3)`; it is not a dimensionless friction factor.

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

Source: PDF pp. 45-47. The reported molar latent heats and duties are

$$
\overline\lambda_D=0.9911(1071.1923)(32)+(1-0.9911)(2309.6661)(18)
\simeq34343.087\ \mathrm{kJ/kmol},
$$

$$
Q_C=\frac{313.474(34343.087)}{3600}\simeq2990.46\ \mathrm{kW},\qquad
\dot m_{cw}=\frac{2990.46}{4.186(35-20)}\simeq47.63\ \mathrm{kg/s}.
$$

$$
\Delta T_{lm}=\frac{(64.59-20)-(64.59-35)}{\ln[(64.59-20)/(64.59-35)]}\simeq36.58\ \mathrm{K},
$$

$$
A_C=\frac{1000(2990.46)}{800(36.58)}\simeq102.19\ \mathrm{m^2}.
$$

The source selects 102.8 m2. Its reboiler estimate uses

$$
Q_R=\frac{313.474(41582.227)}{3600}\simeq3620.82\ \mathrm{kW},\quad
\dot m_{steam}=\frac{3620.82}{2181}\simeq1.6602\ \mathrm{kg/s},
$$

$$
A_R=\frac{1000(3620.82)}{1000(127.44-99.95)}\simeq131.71\ \mathrm{m^2},\quad
A_{R,allow}=1.1A_R\simeq144.881\ \mathrm{m^2}.
$$

The selected area is 158.9 m2 and steam use with allowance is about 1.826 kg/s. Latent heats, U values and the stated steam pressure/temperature pair remain source-reported assumptions; this note does not approve them.

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
d_{in,reflux}=\sqrt{\frac{4(0.001667)}{\pi(1.6)}}\simeq0.03642\ \mathrm{m},\qquad d_{in,selected}=0.038-2(0.003)=0.032\ \mathrm{m}.
$$

Source PDF pp. 49-50 selects the smaller ID32 mm for both reflux and bottoms. Its vapor OD426×12 mm has ID402 mm, although several speed substitutions use 420 mm. These choices require review.
