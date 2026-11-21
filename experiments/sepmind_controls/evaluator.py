"""External evaluator: no runtime reviewer imports, no solver rescue."""
import math, time

def evaluate(record, basis, reference_reflux):
    start=time.monotonic()
    try:
        out=record['outputs'];req=record['request']
        f,d,b=(out[k] for k in ('feed','distillate','bottoms'))
        F,D,B=(v['flow_mol_s'] for v in (f,d,b))
        z,x,y=(v['mole_fractions'] for v in (f,d,b))
        physical=all(math.isfinite(v) for v in [F,D,B,*z,*x,*y,out['condenser_duty_kW'],out['reboiler_duty_kW']])
        physical=physical and min(F,D,B,out['condenser_duty_kW'],out['reboiler_duty_kW'])>0
        physical=physical and all(len(v)==2 and abs(sum(v)-1)<1e-7 and all(0<=a<=1 for a in v) for v in (z,x,y))
        eps_c=max(abs(F*z[i]-D*x[i]-B*y[i])/F for i in range(2))
        eps_m=abs(f['mass_flow_kg_s']-d['mass_flow_kg_s']-b['mass_flow_kg_s'])/f['mass_flow_kg_s']
        h=lambda s:s['mass_flow_kg_s']*s['specific_enthalpy_kJ_kg']
        eps_h=abs(h(f)+out['reboiler_duty_kW']-h(d)-h(b)-out['condenser_duty_kW'])/max(out['condenser_duty_kW'],out['reboiler_duty_kW'],1)
        target=basis.target;zf=basis.feed.composition[0];F0=basis.feed.flow/3.6
        if target.key_component_recovery is not None:
            D0=F0*zf*target.key_component_recovery/target.distillate_mole_fraction
        else:
            D0=F0*(zf-target.bottoms_mole_fraction)/(target.distillate_mole_fraction-target.bottoms_mole_fraction)
        products={'distillate':x[0]>=target.distillate_mole_fraction}
        if target.bottoms_mole_fraction is not None:products['bottoms']=y[0]<=target.bottoms_mole_fraction
        recovery=D*x[0]/(F*z[0])
        if target.key_component_recovery is not None:products['recovery']=recovery>=target.key_component_recovery
        expected_names={'71-43-2':'Benzene','108-88-3':'Toluene','64-17-5':'Ethanol','7732-18-5':'Water','67-56-1':'Methanol'}
        model='NRTL' if basis.thermodynamic_model=='NRTL' else "Raoult's Law"
        R=req['reflux_ratio'];fixed_r=basis.column.reflux_ratio is not None or basis.column.reflux_multiplier is not None
        fixed={
            'feed_flow':abs(F-F0)/F0<=1e-7 and abs(req['feed_molar_flow_mol_s']-F0)/F0<=1e-7,
            'draw':abs(D-D0)/F0<=1e-7 and abs(req['distillate_flow_mol_s']-D0)/F0<=1e-7,
            'composition':abs(z[0]-zf)<=1e-8 and abs(req['feed_light_fraction']-zf)<=1e-8,
            'pressure':abs(req['pressure_pa']-basis.feed.pressure_kPa*1000)<=1e-5,
            'method':req['property_package']==model,
            'identities':list(req['components'])==[expected_names[c.cas or c.canonical_id] for c in basis.components],
            'stages':3<=req['equilibrium_stages']<=basis.column.max_stages and 1<=req['feed_stage']<req['equilibrium_stages'],
            'reflux':abs(R-reference_reflux)<=1e-8*max(reference_reflux,1) if fixed_r else reference_reflux<=R<=reference_reflux*2+1e-10,
            'native_version':str(record.get('version','')).startswith('DWSIM version 9.0.5'),
        }
        closure=eps_c<=1e-4 and eps_m<=1e-4 and eps_h<=1e-4 and abs(F-D-B)/F<=1e-6
        return {'passed':bool(physical and closure and all(products.values()) and all(fixed.values())),
            'physical':bool(physical),'numerical_closure':bool(closure),'strict_targets':products,
            'fixed_constraints':fixed,'fixed_violations':sum(not v for v in fixed.values()),
            'component_residual':eps_c,'mass_residual':eps_m,'energy_residual':eps_h,
            'light_recovery':recovery,'elapsed_s':time.monotonic()-start}
    except (KeyError,TypeError,ValueError,ZeroDivisionError,OverflowError) as exc:
        return {'passed':False,'unscorable':True,'error':type(exc).__name__,
                'elapsed_s':time.monotonic()-start,'fixed_violations':None}
