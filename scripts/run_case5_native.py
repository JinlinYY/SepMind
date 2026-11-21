"""Rebuild FOSSEE 43 with allowlisted native units; never load CAPE binaries.

The source design is a reference, not an autonomous SepMind result. Fixed D/R
come from its converged source state. Each native calculation records its own
products and balances; no source composition is imposed on a product stream.
"""
import argparse
import json
from pathlib import Path
import sys
import re

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sepmind.simulation.multifeed import MultiFeedColumnRequest,ColumnFeed,MultiFeedDwsimBackend


def source_profile(path):
    """Read inert numeric ChemSep text only; rounded profiles are seeds, not data fits."""
    text=path.read_text(encoding='utf8').split('\x00')[0]
    sections={};section=None
    for line in text.splitlines():
        if line.startswith('['):section=line.strip();sections[section]=[]
        elif section and line.strip():sections[section].append(line.strip())
    profiles=[]
    for line in sections['[Profiles]'][1:]:
        values=line.split()
        if len(values)!=6:raise ValueError('Unexpected source profile columns')
        profiles.append(dict(temperature_K=float(values[1]),liquid_flow_mol_s=1000*float(values[4]),
                             vapor_flow_mol_s=1000*float(values[3])))
    for section,key in [('[Liquid phase compositions]','liquid_mole_fractions'),('[Vapour phase compositions]','vapor_mole_fractions')]:
        start=None
        for line in sections[section]:
            if line.startswith('Component'):
                match=re.search(r'(\d+)\s+to\s+(\d+)',line)
                start=int(match.group(1))-1
            else:
                values=line.split();component=int(values[0])-1
                for j,value in enumerate(values[1:]):
                    profiles[start+j].setdefault(key,[0.]*3)[component]=float(value)
        for row in profiles:
            total=sum(row[key])
            if abs(total-1)>1e-7:raise ValueError('Source estimate composition inconsistent')
            # Explicit rounding repair of text estimates, not physical feeds/products.
            row[key]=[x/total for x in row[key]]
    # ChemSep's first V entry is the distillate draw; DWSIM V[0] is an
    # overhead VAPOR outlet. This flowsheet has a total condenser and no such
    # outlet. Keep the actual reflux L[0]; do not seed a fictitious vapor draw.
    profiles[0]['vapor_flow_mol_s']=0.
    return profiles


def source_request(output):
    return MultiFeedColumnRequest(
        property_card_id='mch_toluene_phenol_unifac_v1',purpose='source_reconstruction',
        feeds=[ColumnFeed(feed_id='Solvent',flow_mol_s=50.,
                mole_fractions=[.99980070494987,.00019929502306795,2.7057567235465e-11],
                temperature_K=373.,stage_index=9,source_evidence_id='FOSSEE43:computed_recycle_stream'),
               ColumnFeed(feed_id='Hydrocarbon',flow_mol_s=20.,mole_fractions=[0.,.5,.5],
                temperature_K=384.,stage_index=24,source_evidence_id='FOSSEE43:fresh_feed')],
        pressure_pa=101325.,distillate_flow_mol_s=10.0435037526,reflux_ratio=8.,
        equilibrium_stages=39,save_path=str((output/'reference_C1.dwxmz').resolve()))


def run(request,backend,path):
    path.with_suffix('.request.json').write_text(request.model_dump_json(indent=2),encoding='utf8')
    try:
        result=backend.column(request)
    except Exception as exc:
        result={'success':False,'error':str(exc),'request':request.model_dump()}
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf8')
    outputs=result.get('outputs',{})
    print(json.dumps({'artifact':str(path),'error':result.get('error'),
                     'distillate':outputs.get('distillate'),'bottoms':outputs.get('bottoms'),
                     'checks':result.get('checks')},ensure_ascii=False),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'output/engineering/case5_native_rebuild_20261110')
    parser.add_argument('--timeout',type=float,default=180.)
    parser.add_argument('--recovery',action='store_true')
    parser.add_argument('--warm-source',action='store_true')
    parser.add_argument('--solver',choices=['default','modified_bubble_point','simultaneous_correction'],default='default')
    parser.add_argument('--source-pure-properties',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    backend=MultiFeedDwsimBackend(timeout_s=args.timeout)
    c1path=args.output/'reference_C1.json'
    if args.recovery:
        c1=json.loads(c1path.read_text(encoding='utf8'))
    else:
        request=source_request(args.output).model_copy(update={'solver_preference':args.solver})
        if args.source_pure_properties:request=request.model_copy(update={'property_card_id':'mch_toluene_phenol_source_pure_v2'})
        if args.warm_source:
            source=ROOT/'output/engineering/case5_native_rebuild_20261110/Extractive_Column_source.sep.txt'
            request=request.model_copy(update={'initial_profile':source_profile(source),
                'initial_estimate_source_evidence_id':'FOSSEE43:ChemSep_converged_profile_rounded_text'})
            request=MultiFeedColumnRequest.model_validate(request.model_dump())
        c1=run(request,backend,c1path)
    if not c1.get('outputs'):return 1
    b=c1['outputs']['bottoms']
    c2=MultiFeedColumnRequest(property_card_id=c1['property_card_id'],purpose='source_reconstruction',
        feeds=[ColumnFeed(feed_id='C1_bottoms',flow_mol_s=b['flow_mol_s'],mole_fractions=b['mole_fractions'],
            temperature_K=b['temperature_K'],stage_index=11,source_evidence_id=c1['evidence_id'])],
        pressure_pa=101325.,distillate_flow_mol_s=9.968019,reflux_ratio=.009201958/.009968019,
        equilibrium_stages=19,save_path=str((args.output/'reference_C2.dwxmz').resolve()))
    c2result=run(c2,backend,args.output/'reference_C2.json')
    return 0 if c2result.get('outputs') else 1


if __name__=='__main__':raise SystemExit(main())
