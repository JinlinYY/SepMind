"""Independent component-flow and NRTL-formula review of saved extraction output."""
import numpy as np


def independent_lngamma(x,T,card):
    x=np.asarray(x,dtype=float);b=np.asarray(card['B_K'])
    if card.get('temperature_parameter_knots'):
        k=card['temperature_parameter_knots']
        pair=next((a,c) for a,c in zip(k,k[1:]) if a['temperature_K']<=T<=c['temperature_K'])
        a,c=pair;w=(T-a['temperature_K'])/(c['temperature_K']-a['temperature_K'])
        b=(1-w)*np.array(a['B_K'])+w*np.array(c['B_K'])
    tau=np.array(card['A'])+b/T;G=np.exp(-np.array(card['alpha'])*tau)
    denom=x@G;weighted=(x@(tau*G))/denom
    return weighted+np.sum((G*x[None,:]/denom[None,:])*(tau-weighted[None,:]),axis=1)


def review_extraction(raw,model,T,expected_feed=None,expected_solvent=None,solute_index=None):
    """Recompute conservation, network connections and reported quantities.

    Stage balances alone cannot detect swapped/disconnected stage streams.
    Expected inlet vectors come from the frozen design basis, not the result.
    """
    issues=[];n=len(model.order)
    def vector(value):
        v=np.asarray(value,dtype=float)
        if v.shape!=(n,) or not np.isfinite(v).all() or np.min(v)<0:
            raise ValueError('invalid component flows')
        return v
    try:
        f,s,e,r=[vector(raw[k]) for k in ('feed_kmol_h','solvent_kmol_h','extract_kmol_h','raffinate_kmol_h')]
        scale=float(sum(f+s))
        if scale<=0 or min(sum(e),sum(r))<=0:raise ValueError('nonpositive total flow')
        profiles=raw['profiles'];count=raw['stages'];configuration=raw['configuration']
        if type(count) is not int or not 1<=count<=30 or len(profiles)!=count:
            raise ValueError('stage profile count')
        if configuration not in ('countercurrent','crosscurrent'):raise ValueError('unsupported stage topology')
        incoming=[];rr=[];ee=[]
        for i,stage in enumerate(profiles):
            if stage['stage']!=i+1:raise ValueError('stage sequence')
            incoming.append(vector(stage['inlet_kmol_h']))
            rr.append(vector(stage['raffinate_kmol_h']));ee.append(vector(stage['extract_kmol_h']))
            if min(sum(rr[-1]),sum(ee[-1]))<=0:raise ValueError('nonpositive phase flow')
        closure=float(max(abs(f+s-e-r))/scale)
        if closure>1e-7:issues.append('overall component closure')
        for expected,actual in ((expected_feed,f),(expected_solvent,s)):
            if expected is not None and max(abs(vector(expected)-actual))/scale>1e-9:
                issues.append('frozen inlet mismatch')
        stage_closure=phase_residual=connection_residual=0.
        for i in range(count):
            stage_closure=max(stage_closure,float(max(abs(incoming[i]-rr[i]-ee[i]))/scale))
            expected=(f if i==0 else rr[i-1])+(s if i==count-1 else ee[i+1]) if configuration=='countercurrent' else (f if i==0 else rr[i-1])+s/count
            connection_residual=max(connection_residual,float(max(abs(incoming[i]-expected))/scale))
            x=rr[i]/sum(rr[i]);y=ee[i]/sum(ee[i])
            if min(x)<=0 or min(y)<=0:raise ValueError('zero activity is outside the admitted interior LLE domain')
            if max(abs(x-y))<1e-5:issues.append('degenerate identical liquid phases')
            residual=float(max(abs(np.log(x)+independent_lngamma(x,T,model.card)-np.log(y)-independent_lngamma(y,T,model.card))))
            phase_residual=max(phase_residual,residual)
        expected_extract=ee[0] if configuration=='countercurrent' else np.sum(ee,axis=0)
        connection_residual=max(connection_residual,float(max(abs(r-rr[-1]))/scale),float(max(abs(e-expected_extract))/scale))
        if stage_closure>1e-7:issues.append('stage component closure')
        if connection_residual>1e-7:issues.append('stage interconnection or endpoint mismatch')
        if phase_residual>1e-5:issues.append('independent NRTL activity equality')
        for label,value in (('extract',e),('raffinate',r)):
            mass=float(value@model.mw);fractions=value*model.mw/mass
            reported_mass=float(raw[label+'_mass_flow_kg_h'])
            if not np.isfinite(reported_mass) or abs(reported_mass-mass)/max(mass,1)>1e-8:
                issues.append(label+' reported mass flow mismatch')
            if np.max(abs(vector(raw[label+'_mass_fractions'])-fractions))>1e-8:
                issues.append(label+' reported composition mismatch')
        if solute_index is not None:
            if f[solute_index]<=0:raise ValueError('no feed solute')
            recovery=(e[solute_index]-s[solute_index])/f[solute_index]
            reported_recovery=float(raw['solute_extraction_recovery'])
            if not np.isfinite(reported_recovery) or abs(recovery-reported_recovery)>1e-8:
                issues.append('reported recovery mismatch')
        return {'passed':not issues,'issues':sorted(set(issues)),'maximum_component_residual':closure,
                'maximum_stage_component_residual':stage_closure,'maximum_connection_residual':connection_residual,
                'maximum_independent_log_activity_residual':phase_residual,
                'scope':'independent formula, network and conservation review; no independent experimental validation of final equipment or energy'}
    except (ValueError,KeyError,TypeError,IndexError,OverflowError) as exc:
        return {'passed':False,'issues':sorted(set(issues+[str(exc)])),
                'scope':'Malformed or inconsistent extraction record rejected before acceptance'}
