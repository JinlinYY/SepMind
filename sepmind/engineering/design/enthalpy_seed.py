"""Energy-coupled binary shooting initializer from native equilibrium enthalpies.

Conservation equations generate numerical guesses for DWSIM. They are never
reported as an accepted native column calculation. Equal-pressure equilibrium
stages, total condenser, partial reboiler, adiabatic trays and q=1 are assumed.
"""
import math
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq


def coupled_initial_profile(points,balance,reflux,count,feed):
    xs=np.array([p['x'][0] for p in points]);ys=np.array([p['y'][0] for p in points])
    yofx=PchipInterpolator(xs,ys,extrapolate=False)
    xofy=PchipInterpolator(ys,xs,extrapolate=False)
    hL=PchipInterpolator(xs,[p['liquid_enthalpy_kJ_mol'] for p in points],extrapolate=False)
    hV=PchipInterpolator(ys,[p['vapor_enthalpy_kJ_mol'] for p in points],extrapolate=False)
    temp=PchipInterpolator(xs,[p['temperature_k'] for p in points],extrapolate=False)
    F,D,B=[balance[k]/3.6 for k in ('F_kmol_h','D_kmol_h','B_kmol_h')]
    z=balance['zF'];hf=float(hL(z))

    def shoot(xd,full=False):
        xb=(F*z-D*xd)/B
        if not xs[0]<xb<z<xd<xs[-1]:return {'residual':1.,'reason':'invalid trial split'}
        hd,hb=float(hL(xd)),float(hL(xb))
        qc=(reflux+1)*D*(float(hV(xd))-hd)
        qr=D*hd+B*hb+qc-F*hf
        profile=[{'temperature_K':float(temp(xd)), 'liquid_flow_mol_s':reflux*D,
                  'vapor_flow_mol_s':0.,'liquid_light_fraction':xd,'vapor_light_fraction':xd}]
        y=xd;vcurrent=(reflux+1)*D
        for stage in range(1,count+1):
            x=float(xofy(y))
            if not math.isfinite(x):return {'residual':1.,'reason':'equilibrium interpolation domain'}
            if x<=xb and stage<count:
                return {'residual':min(x-xb,-1e-9),'reason':'target reached before partial reboiler'}
            row={'temperature_K':float(temp(x)),'liquid_light_fraction':x,
                 'vapor_light_fraction':y,'vapor_flow_mol_s':vcurrent}
            if stage==count:
                row['liquid_flow_mol_s']=B;profile.append(row)
                return {'residual':x-xb,'profile':profile,'distillate_x':xd,'bottoms_x':xb,
                        'condenser_duty_kW':qc,'reboiler_duty_kW':qr}
            hl=float(hL(x))
            if stage<feed:
                factor=xd-x;delta=hd-hl+qc/D
            else:
                factor=x-xb;delta=qr/B+hl-hb
            def equation(ynext):
                return factor*(float(hV(ynext))-hl)-delta*(ynext-x)
            low=max(x+1e-10,float(ys[0])+1e-10)
            high=y-1e-10
            if low>=high or not math.isfinite(equation(low)+equation(high)) or equation(low)*equation(high)>0:
                return {'residual':max(x-xb,1e-9),'reason':'enthalpy-coupled pinch/no descending operating intersection'}
            ynext=brentq(equation,low,high,xtol=1e-12)
            vnext=(D*(xd-x)/(ynext-x) if stage<feed else B*(x-xb)/(ynext-x))
            liquid=vnext-D if stage<feed else vnext+B
            if min(liquid,vnext)<=0:
                return {'residual':1.,'reason':'negative internal flow rejected'}
            row['liquid_flow_mol_s']=liquid;profile.append(row)
            y,vcurrent=ynext,vnext
        raise AssertionError('unreachable')

    lower=max(z+1e-5,balance['xD']-.04,float(ys[0])+1e-5)
    upper=min(F*z/D-1e-7,1-1e-6,float(ys[-1])-1e-6)
    signals=[x for x,y in zip(xs,ys) if x>balance['xD'] and y<=x]
    if signals:upper=min(upper,min(signals)-1e-6)
    trials=[];root=None
    for xd in np.linspace(lower,upper,61):
        result=shoot(float(xd));res=result['residual']
        if trials and trials[-1][1]*res<0:
            candidate=brentq(lambda x:shoot(x)['residual'],trials[-1][0],float(xd),xtol=1e-11)
            candidate_result=shoot(candidate,True)
            if 'profile' in candidate_result and abs(candidate_result['residual'])<1e-6:
                root=candidate_result;break
        trials.append((float(xd),res))
    if root is None:
        return {'status':'no_seed','reason':'No physically positive fixed-design shooting root within the admitted enrichment interval',
                'trial_count':len(trials)}
    profile=root['profile'];xd=root['distillate_x'];xb=root['bottoms_x']
    residuals={'total':[],'component':[],'energy':[],'equilibrium':[]}
    for i in range(1,count+1):
        a,p=profile[i-1],profile[i]
        Lin=a['liquid_flow_mol_s'];xin=a['liquid_light_fraction']
        Vout=p['vapor_flow_mol_s'];yout=p['vapor_light_fraction']
        if i==count:
            total=Lin-B-Vout;component=Lin*xin-B*xb-Vout*yout
            energy=Lin*float(hL(xin))+root['reboiler_duty_kW']-B*float(hL(xb))-Vout*float(hV(yout))
        else:
            nxt=profile[i+1];Vin=nxt['vapor_flow_mol_s'];yin=nxt['vapor_light_fraction']
            Lout=p['liquid_flow_mol_s'];xout=p['liquid_light_fraction'];f=F if i==feed else 0.
            total=Lin+Vin+f-Lout-Vout
            component=Lin*xin+Vin*yin+f*z-Lout*xout-Vout*yout
            energy=Lin*float(hL(xin))+Vin*float(hV(yin))+f*hf-Lout*float(hL(xout))-Vout*float(hV(yout))
        residuals['total'].append(abs(total)/F)
        residuals['component'].append(abs(component)/F)
        residuals['energy'].append(abs(energy)/max(root['condenser_duty_kW'],root['reboiler_duty_kW'],1.))
        residuals['equilibrium'].append(abs(float(yofx(p['liquid_light_fraction']))-yout))
    maxima={k:max(v) for k,v in residuals.items()}
    passed=max(maxima.values())<2e-5
    return {'status':'initial_guess' if passed else 'rejected_guess','profile':profile if passed else None,
            'initial_distillate_x':xd,'initial_bottoms_x':xb,'residuals':maxima,
            'condenser_duty_kW':root['condenser_duty_kW'],'reboiler_duty_kW':root['reboiler_duty_kW'],
            'meaning':'interpolated native-property conservation solution for initialization only; NOT an accepted DWSIM column result'}
