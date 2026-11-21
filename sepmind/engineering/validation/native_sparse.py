"""Registered numerical solver for DWSIM's own MESH equations.

No thermodynamic or physical residual is replaced. SciPy supplies sparse finite
differences/trust-region steps through DWSIM's external-solver interface.
"""
from pathlib import Path
import math
import sys
import time
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix


def register_sparse_solver(flow,column,request,Array,Double):
    import clr
    root=Path(__file__).resolve().parents[3]
    assembly=root/'.runtime/dwsim/SepMindSolverBridge.dll'
    if not assembly.exists():raise FileNotFoundError('Build the registered engineering/native/SepMindSolverBridge.cs adapter first')
    clr.AddReference(str(assembly))
    from SepMind.Native import NonlinearBridge,NonlinearCallback
    components=len(request.components);records=[];block=2*components+1
    stripper=request.column_mode=='reboiled_absorber'

    def solve(function,gradient,iteration,initial,max_iterations,tolerance):
        x0=np.asarray(list(initial));size=len(x0)
        if size%block:raise ValueError('Unexpected DWSIM MESH equation layout')
        stages=size//block;pattern=lil_matrix((size,size),dtype=int)
        for i in range(stages):
            pattern[i*block:(i+1)*block,max(0,i-1)*block:min(stages,i+2)*block]=1
        # The registered specs are reflux ratio at the top and bottom molar
        # draw. Both are local endpoint constraints; no recovery or global
        # heat-duty specs are admitted by this adapter.
        weights=np.ones(size)
        for i in range(stages):
            # Native residual layout multiplies M by 1e6, but leaves E and
            # scaled H unmultiplied. Undo that numerical multiplier; do not
            # suppress energy/specification equations relative to M and E.
            weights[i*block+1:i*block+1+components]=1e-6
        cold_policy=request.initial_profile is None
        if cold_policy:
            # Retain the cold-start policy actually cross-checked against a
            # native solved control. Seeded large-column policies are separate
            # experiments and do not replace this verified numerical setting.
            for i in range(stages):
                weights[i*block+1:i*block+1+components]=1e-3
                weights[i*block+1+components:(i+1)*block]=1e3
        calls=0;started=time.monotonic()

        def raw(x):
            nonlocal calls
            calls+=1
            value=np.asarray(list(function.Invoke(Array[Double](x.tolist()))),dtype=float)
            if value.shape!=(size,) or not np.isfinite(value).all():raise ValueError('Nonfinite native MESH residual')
            return value

        # Native NS runs a four-step bubble-point initializer before invoking
        # external solvers. Restore a source-tagged native profile in the NS
        # coordinates when supplied, so a poor initializer cannot discard it.
        # These are numerical guesses only; every residual remains native.
        from System.Reflection import BindingFlags
        flags=BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public
        native_solver=column.Solver
        def field(name):
            f=native_solver.GetType().GetField(name,flags)
            if f is None:raise ValueError('Unsupported native MESH normalization layout: '+name)
            return f.GetValue(native_solver)
        max_t=float(field('_maxT'))
        max_v,max_l=float(field('_maxvc')),float(field('_maxlc'))
        flow_scale=sum(float(v) for v in field('_F'))/request.feed_molar_flow_mol_s
        order=[request.components.index(str(n)) for n in flow.SelectedCompounds.Keys]
        from sepmind.simulation.mixture import mixture_card
        temperature_guard=getattr(request,'temperature_guard_K',None)
        if temperature_guard is None:
            card,_=mixture_card(request.property_card_id)
            temperature_guard=card['temperature_guard_K']
        lower=np.full(size,1e-30);upper=np.full(size,np.inf)
        lower[::block]=temperature_guard[0]/max_t
        upper[::block]=temperature_guard[1]/max_t
        estimate=x0.copy();seed_mapping=None
        if request.initial_profile:
            max_v,max_l=float(field('_maxvc')),float(field('_maxlc'))
            flow_scale=sum(float(v) for v in field('_F'))/request.feed_molar_flow_mol_s
            if not all(math.isfinite(v) and v>0 for v in (max_t,max_v,max_l,flow_scale)) or min(abs(flow_scale-.001),abs(flow_scale-1.))>1e-9:
                raise ValueError('Unsupported native MESH flow normalization')
            order=[request.components.index(str(n)) for n in flow.SelectedCompounds.Keys]
            for i,row in enumerate(request.initial_profile):
                estimate[i*block]=row['temperature_K']/max_t
                for j,k in enumerate(order):
                    # NS represents the condenser product by vc[0], even though
                    # there is no external overhead-vapor port in this design.
                    v=request.distillate_flow_mol_s*row['liquid_mole_fractions'][k] if i==0 and not stripper else row['vapor_flow_mol_s']*row['vapor_mole_fractions'][k]
                    l=row['liquid_flow_mol_s']*row['liquid_mole_fractions'][k]
                    estimate[i*block+j+1]=v*flow_scale/max_v
                    estimate[i*block+j+1+components]=l*flow_scale/max_l
            seed_mapping={'source_evidence_id':request.initial_estimate_source_evidence_id,
                          'native_temperature_scale':max_t,'native_vapor_scale':max_v,'native_liquid_scale':max_l,
                          'native_flow_unit_ratio':flow_scale,'condenser_vc0':'distillate component flow, not a physical vapor outlet'}
        estimate=np.maximum(estimate,np.nextafter(lower,np.inf) if stripper else lower+1e-16)
        estimate=np.minimum(estimate,upper-1e-16)
        if cold_policy and request.numerical_jacobian_policy!='balanced_reduced':
            lower=np.full(size,1e-20);upper=np.full(size,2.)
            estimate=np.clip(x0,1e-16,2.-1e-12)
        if cold_policy and request.numerical_jacobian_policy=='balanced_reduced':
            # Project native initializer estimates, without treating them as
            # calculated products. Physical feed vectors remain unchanged.
            from .initialization import material_consistent_profile
            rows=[]
            for i,a in enumerate(estimate.reshape(stages,block)):
                v=a[1:components+1]*max_v/flow_scale;l=a[components+1:]*max_l/flow_scale
                xx=np.zeros(components);yy=xx.copy()
                xx[order]=l/sum(l);yy[order]=v/sum(v)
                rows.append(dict(temperature_K=float(a[0]*max_t),liquid_flow_mol_s=float(sum(l)),vapor_flow_mol_s=0. if i==0 and not stripper else float(sum(v)),
                                 liquid_mole_fractions=xx.tolist(),vapor_mole_fractions=yy.tolist()))
            seed_request=request.model_copy(update={'initial_profile':rows,'initial_estimate_source_evidence_id':'native_initializer_not_a_product'})
            rows,projection=material_consistent_profile(seed_request)
            for i,row in enumerate(rows):
                estimate[i*block]=row['temperature_K']/max_t
                estimate[i*block+1:i*block+1+components]=(request.distillate_flow_mol_s if i==0 else row['vapor_flow_mol_s'])*np.asarray(row['vapor_mole_fractions'])[order]*flow_scale/max_v
                estimate[i*block+1+components:(i+1)*block]=row['liquid_flow_mol_s']*np.asarray(row['liquid_mole_fractions'])[order]*flow_scale/max_l
            seed_mapping={'source':'native four-step initializer, unaccepted numerical estimates','material_projection':projection}
        record={'algorithm':'scipy_sparse_trust_region_on_native_DWSIM_MESH',
                'variables':size,'native_tolerance':float(tolerance),'accepted':False,'initial_estimate_mapping':seed_mapping,
                'numerical_policy':'cold_control_v1' if cold_policy else 'seeded_experimental_v3'}
        records.append(record)
        try:
            initial_residual=raw(estimate)
            if stripper:
                record['native_boundary_terms']={name:[float(v) for v in field(name)]
                    for name in ('_Q','_VSS','_LSS','_F','_eff')}
                record['native_feed_compositions']=[[float(v) for v in row] for row in field('_fc')]
                record['native_bottom_specification_mol_s']=float(field('_spval2'))
                record['native_pressure_profile_Pa']=[float(v) for v in field('_P')]
                record['initial_residual_blocks']=initial_residual.reshape(stages,block).tolist()
                native_pp=field('_pp');diagnostics=[]
                for i in (0,stages-1):
                    a=estimate.reshape(stages,block)[i];v=a[1:components+1]*max_v;l=a[components+1:]*max_l
                    k=native_pp.DW_CalcKvalue(Array[Double]((l/sum(l)).tolist()),Array[Double]((v/sum(v)).tolist()),float(a[0]*max_t),float(field('_P')[i]))
                    diagnostics.append(dict(stage=i,temperature_K=float(a[0]*max_t),K=list(k)))
                record['native_K_diagnostics']=diagnostics
            record['initial_native_residual_by_kind']={
                'H':float(max(abs(initial_residual[::block]))),
                'M_unscaled':float(max(abs(initial_residual.reshape(stages,block)[:,1:1+components]).ravel()))/1e6,
                'E':float(max(abs(initial_residual.reshape(stages,block)[:,1+components:]).ravel()))}
            print('native_sparse: initial '+str(record['initial_native_residual_by_kind']),file=sys.stderr,flush=True)
            if request.numerical_jacobian_policy=='log_mesh':
                component_feed=np.zeros(components)
                for feed in request.feeds:component_feed+=feed.flow_mol_s*np.asarray(feed.mole_fractions)[order]*flow_scale
                if min(component_feed)<=0:raise ValueError('Every declared stripper species must be present')
                def log_residual(logx):
                    x=np.exp(logx);r=raw(x).reshape(stages,block)
                    v=x.reshape(stages,block)[:,1:components+1]*max_v
                    r[:,1:components+1]/=1e6*component_feed[None,:]
                    r[:,1+components:]/=np.maximum(v,1e-25)
                    r[:,0]/=max(request.feed_molar_flow_mol_s/20,1.)
                    # Native bottom H is log(B/Bspec)/Bspec, not an energy row.
                    r[-1,0]*=(request.feed_molar_flow_mol_s-request.distillate_flow_mol_s)*max(request.feed_molar_flow_mol_s/20,1.)
                    return r.ravel()
                ls=least_squares(log_residual,np.log(estimate),bounds=(np.log(lower),np.log(np.where(np.isfinite(upper),upper,1e6))),
                    jac_sparsity=pattern.tocsr(),x_scale='jac',diff_step=1e-6,tr_options={'atol':1e-12,'btol':1e-12,'maxiter':size*3},
                    ftol=1e-12,xtol=1e-12,gtol=1e-12,max_nfev=min(int(max_iterations),500))
                final_x=np.exp(ls.x);final=raw(final_x);sse=float(final@final)
                record.update(jacobian_policy='Logarithmic positive coordinates on native stripper MESH',
                              scaled_residual_maximum=float(max(abs(log_residual(ls.x)))),native_residual_sum_squares=sse)
                if sse>float(tolerance):
                    # The positive solve can locate a nearby equilibrium while
                    # component conservation remains below native acceptance.
                    # Project only its numerical guesses, then solve the native
                    # equations again with balances exactly eliminated.
                    from .initialization import material_consistent_profile
                    from .balanced_mesh import balanced_newton
                    rows=[]
                    for a in final_x.reshape(stages,block):
                        v=a[1:components+1]*max_v/flow_scale;l=a[components+1:]*max_l/flow_scale
                        xx=np.zeros(components);yy=xx.copy();xx[order]=l/sum(l);yy[order]=v/sum(v)
                        rows.append(dict(temperature_K=float(a[0]*max_t),liquid_flow_mol_s=float(sum(l)),vapor_flow_mol_s=float(sum(v)),
                                         liquid_mole_fractions=xx.tolist(),vapor_mole_fractions=yy.tolist()))
                    record['unaccepted_numerical_profile']=rows
                    feeds=np.zeros((stages,components))
                    for feed in request.feeds:feeds[feed.stage_index]+=feed.flow_mol_s*np.asarray(feed.mole_fractions)[order]*flow_scale
                    from .positive_balance_seed import positive_balance_seed
                    guess,projection=positive_balance_seed(final_x,feeds,max_v,max_l,
                        (request.feed_molar_flow_mol_s-request.distillate_flow_mol_s)*flow_scale)
                    record['polish_initialization_projection']=projection
                    vapor=final_x.reshape(stages,block)[:,1:components+1]*max_v
                    row_weights=np.r_[np.full(stages,1/max(request.feed_molar_flow_mol_s/20,1.)),1/np.maximum(vapor,1e-20).ravel()]
                    row_weights[stages-1]=request.feed_molar_flow_mol_s-request.distillate_flow_mol_s
                    variable_scales=np.r_[np.ones(stages),np.tile(feeds.sum(axis=0)/max_l,stages)]
                    final_x,history,_=balanced_newton(raw,guess,feeds,max_v,max_l,0.,lower,upper,float(tolerance),50,reboiled_absorber=True,
                        residual_weights=row_weights,coordinate_scales=variable_scales)
                    final=raw(final_x);sse=float(final@final)
                    record.update(polish_history=history,native_residual_sum_squares=sse)
                if sse>float(tolerance):raise ValueError('Log native MESH acceptance not reached: '+str(sse))
                record['accepted']=True
                return Array[Double](final_x.tolist())
            # Trace-component/native bottom-draw equations can have tiny raw
            # SSE while their relative error is still unacceptable. Keep the
            # strict scaled solve for these research cases, including restart.
            positive_initialization=getattr(request,'positive_balance_initialization',False)
            strict_scaled = stripper or request.property_card_id=='mch_toluene_sulfolane_vle_brouwer2021' or positive_initialization
            if float(initial_residual@initial_residual)<=float(tolerance) and not strict_scaled:
                record.update(accepted=True,scipy_success=None,termination='Source-tagged seed already meets native MESH tolerance',
                              native_residual_sum_squares=float(initial_residual@initial_residual))
                return Array[Double](estimate.tolist())
            if request.numerical_jacobian_policy=='balanced_reduced':
                from .balanced_mesh import balanced_newton
                feeds=np.zeros((stages,components))
                for feed in request.feeds:
                    feeds[feed.stage_index]=feeds[feed.stage_index]+feed.flow_mol_s*np.asarray(feed.mole_fractions)[order]*flow_scale
                options={}
                if getattr(request,'positive_balance_initialization',False) and not stripper:
                    from .positive_balance_seed import positive_balance_seed
                    estimate,projection=positive_balance_seed(estimate,feeds,max_v,max_l,
                        (request.feed_molar_flow_mol_s-request.distillate_flow_mol_s)*flow_scale,
                        reflux_ratio=request.reflux_ratio,allow_feasible_fallback=positive_initialization)
                    record['positive_balance_projection']=projection
                if stripper:
                    from .positive_balance_seed import positive_balance_seed
                    vapor=estimate.reshape(stages,block)[:,1:components+1]*max_v
                    row_weights=np.r_[np.full(stages,1/max(request.feed_molar_flow_mol_s/20,1.)),1/np.maximum(vapor,1e-20).ravel()]
                    row_weights[stages-1]=request.feed_molar_flow_mol_s-request.distillate_flow_mol_s
                    variable_scales=np.r_[np.ones(stages),np.tile(feeds.sum(axis=0)/max_l,stages)]
                    estimate,projection=positive_balance_seed(estimate,feeds,max_v,max_l,
                        (request.feed_molar_flow_mol_s-request.distillate_flow_mol_s)*flow_scale)
                    record['positive_balance_projection']=projection
                    record['balanced_newton_audit']={}
                    options=dict(residual_weights=row_weights,coordinate_scales=variable_scales,audit=record['balanced_newton_audit'])
                elif (request.property_card_id=='mch_toluene_sulfolane_vle_brouwer2021' or positive_initialization) and min(feeds.sum(axis=0))>0:
                    vapor=estimate.reshape(stages,block)[1:,1:components+1]*max_v
                    trace_floor=max(1e-20,request.feed_molar_flow_mol_s*flow_scale*1e-12) if positive_initialization else 1e-20
                    row_weights=np.r_[np.full(stages-1,1/max(request.feed_molar_flow_mol_s/20,1.)),1.,1/np.maximum(vapor,trace_floor).ravel()]
                    row_weights[stages-2]=request.feed_molar_flow_mol_s-request.distillate_flow_mol_s
                    variable_scales=np.r_[np.ones(stages),np.tile(feeds.sum(axis=0)/max_l,stages-1)]
                    record['balanced_newton_audit']={}
                    options=dict(residual_weights=row_weights,coordinate_scales=variable_scales,audit=record['balanced_newton_audit'])
                try:
                    options['trace_relative_finite_differences']=getattr(request,'trace_relative_finite_differences',False)
                    record['finite_difference_policy']='trace-relative/bidirectional' if options['trace_relative_finite_differences'] else 'retained_absolute_floor'
                    solution,history,evaluations=balanced_newton(raw,estimate,feeds,max_v,max_l,request.reflux_ratio,lower,upper,
                                                                float(tolerance),int(max_iterations),reboiled_absorber=stripper,**options)
                except ValueError as error:
                    audit=options.get('audit',{})
                    if not positive_initialization or 'last_unaccepted_coordinates' not in audit:
                        raise
                    solution=np.asarray(audit['last_unaccepted_coordinates'],dtype=float)
                    residual=raw(solution)
                    if float(residual@residual)>float(tolerance):
                        raise
                    history=audit['history'];evaluations=calls
                    record['termination']={'native_tolerance_met':True,'extra_scaled_stop_error':str(error),
                        'independent_phase_and_balance_review_required':True}
                final=raw(solution)
                record.update(accepted=True,jacobian_policy='Linear stage balances eliminated; damped native Newton',
                              newton_history=history,native_residual_sum_squares=float(final@final))
                return Array[Double](solution.tolist())
            options={} if cold_policy else {'tr_options':{'atol':1e-12,'btol':1e-12,'maxiter':size*2}}
            if request.numerical_jacobian_policy=='native_dense':
                def native_gradient(x):
                    matrix=gradient.Invoke(Array[Double](x.tolist()))
                    values=np.asarray(list(matrix),dtype=float).reshape(size,size)
                    if not np.isfinite(values).all():raise ValueError('Nonfinite native Jacobian')
                    record['native_gradient_calls']=record.get('native_gradient_calls',0)+1
                    return weights[:,None]*values
                record['jacobian_policy']='Native DWSIM derivative callback; dense trust region'
                options={'jac':native_gradient,'tr_solver':'exact'}
            else:options.update(jac='2-point',jac_sparsity=pattern.tocsr(),tr_solver='lsmr',diff_step=1e-5)
            solution=least_squares(lambda x:weights*raw(x),estimate,
                bounds=(lower,upper),method='trf',x_scale='jac',ftol=1e-12,xtol=1e-12,gtol=1e-12,
                max_nfev=min(int(max_iterations),300),**options)
            final=raw(solution.x);sse=float(final@final)
            record.update(scipy_success=bool(solution.success),termination=str(solution.message),
                          native_residual_sum_squares=sse,maximum_native_residual=float(max(abs(final))))
            if not math.isfinite(sse) or sse>float(tolerance):
                raise ValueError('Native MESH acceptance not reached by sparse solver: '+str(sse))
            record['accepted']=True
            return Array[Double](solution.x.tolist())
        finally:
            record.update(native_residual_evaluations=calls,elapsed_s=time.monotonic()-started)
            print('native_sparse: '+str(record),file=sys.stderr,flush=True)

    delegate=NonlinearCallback(solve);bridge=NonlinearBridge();bridge.Callback=delegate
    identity='sepmind_sparse_trust_region_v1'
    flow.ExternalSolvers.Add(identity,bridge);column.ExternalSolverID=identity
    # Retain managed/Python delegate references throughout the column solve.
    return {'bridge':bridge,'delegate':delegate,'records':records}
