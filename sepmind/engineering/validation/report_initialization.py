"""Recover rounded numerical estimates from an UNACCEPTED native solver log.

This is initialization only. No row is an accepted unit result, and the next
native solve plus independent review are mandatory.
"""
import math


def profile_from_native_report(report,stages,components,*,total_condenser=True):
    lines=[s.strip() for s in report.splitlines() if s.strip()]
    def block(title,width):
        positions=[i for i,line in enumerate(lines) if line==title]
        if not positions:raise ValueError('Missing native estimate section: '+title)
        rows=[]
        for line in lines[positions[-1]+1:]:
            try:values=[float(v) for v in line.split()]
            except ValueError:
                if rows:break
                continue
            if len(values)!=width or int(values[0])!=len(rows)+1:raise ValueError('Unexpected native numerical report layout')
            if not all(math.isfinite(v) for v in values):raise ValueError('Nonfinite native estimates')
            rows.append(values)
            if len(rows)==stages:break
        if len(rows)!=stages:raise ValueError('Incomplete numerical estimate report')
        return rows
    conditions=block('Stage Conditions & Flows',6)
    liquid=block('Stage Molar Fractions - Liquid 1',components+1)
    vapor=block('Stage Molar Fractions - Vapor',components+1)
    output=[]
    for i,row in enumerate(conditions):
        out=dict(temperature_K=row[2],vapor_flow_mol_s=0. if total_condenser and i==0 else row[3],liquid_flow_mol_s=row[4])
        for values,key in [(liquid[i][1:],'liquid_mole_fractions'),(vapor[i][1:],'vapor_mole_fractions')]:
            if min(values)<0 or abs(sum(values)-1)>2e-5:raise ValueError('Composition estimate is not normalized within report rounding')
            out[key]=[v/sum(values) for v in values]
        output.append(out)
    return output
