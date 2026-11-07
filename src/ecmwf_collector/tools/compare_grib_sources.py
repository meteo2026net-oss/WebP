"""Metadata and numeric comparison of WMO and ECMWF Open Data GRIB fields."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import numpy as np

def _key(da,name):
    a=da.attrs; v=da.coords.get("valid_time")
    t=str(np.asarray(v.values).ravel()[0]) if v is not None else ""
    return (str(a.get("GRIB_paramId",a.get("paramId",name))),str(a.get("GRIB_typeOfLevel",a.get("typeOfLevel",""))),str(a.get("GRIB_level",a.get("level",""))),t)

def _fields(path):
    import cfgrib
    found={}
    for ds in cfgrib.open_datasets(str(path),backend_kwargs={"indexpath":""}):
        try:
            for name in ds.data_vars: found[_key(ds[name],name)]=(name,ds[name].load())
        finally: ds.close()
    return found

def _metrics(left,right):
    if left.shape!=right.shape: return {"comparable":False,"reason":"shape_mismatch"}
    for coord in ("latitude","longitude"):
        if coord not in left.coords or coord not in right.coords: return {"comparable":False,"reason":"missing_"+coord}
        x,y=np.asarray(left[coord].values),np.asarray(right[coord].values)
        if x.shape!=y.shape or not np.allclose(x,y,rtol=0,atol=1e-6,equal_nan=True):
            return {"comparable":False,"reason":coord+"_grid_mismatch"}
    if left.attrs.get("units")!=right.attrs.get("units"):
        return {"comparable":False,"reason":"unit_mismatch","wmo_units":left.attrs.get("units"),"ecmwf_units":right.attrs.get("units")}
    a,b=np.asarray(left.values,dtype=float),np.asarray(right.values,dtype=float)
    mask=np.isfinite(a)&np.isfinite(b); n=int(mask.sum())
    if not n: return {"comparable":False,"reason":"no_common_finite_values"}
    d=b[mask]-a[mask]; corr=None
    if n>1 and np.std(a[mask])>0 and np.std(b[mask])>0: corr=float(np.corrcoef(a[mask],b[mask])[0,1])
    return {"comparable":True,"grid_points":int(a.size),"common_valid_points":n,
      "coverage_percent":round(100*n/a.size,4),"units":left.attrs.get("units"),
      "bias_ecmwf_minus_wmo":float(np.mean(d)),"mae":float(np.mean(np.abs(d))),
      "rmse":float(np.sqrt(np.mean(d*d))),"max_abs_difference":float(np.max(np.abs(d))),
      "correlation":corr}

def _sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(4*1024*1024),b""): h.update(block)
    return h.hexdigest()

def compare_grib_files(wmo_path,ecmwf_path):
    from ecmwf_collector.fileinspect import inspect_file
    w,e=Path(wmo_path),Path(ecmwf_path); wi,ei=inspect_file(w),inspect_file(e)
    out={"sources":{"wmo":"WMO Support Dataset","ecmwf":"ECMWF Open Data"},
      "files":{"wmo":{"name":w.name,"bytes":w.stat().st_size,"integrity":wi.verdict,"messages":wi.messages},
      "ecmwf":{"name":e.name,"bytes":e.stat().st_size,"integrity":ei.verdict,"messages":ei.messages}},
      "same_sha256":_sha(w)==_sha(e),"matches":[],"only_wmo":[],"only_ecmwf":[],"warnings":[]}
    if wi.verdict!="ok" or ei.verdict!="ok":
        out["warnings"].append("لم تُحسب الفروق العددية لأن أحد الملفين لم يجتز فحص البنية."); return out
    left,right=_fields(w),_fields(e); common=sorted(set(left)&set(right),key=str)
    out["only_wmo"]=[list(k) for k in sorted(set(left)-set(right),key=str)]
    out["only_ecmwf"]=[list(k) for k in sorted(set(right)-set(left),key=str)]
    for k in common:
        ln,ld=left[k]; rn,rd=right[k]
        out["matches"].append({"field_key":list(k),"wmo_variable":ln,"ecmwf_variable":rn,**_metrics(ld,rd)})
    out["quality_summary"]={"matched_fields":len(common),
      "comparable_fields":sum(x.get("comparable",False) for x in out["matches"]),
      "non_comparable_fields":sum(not x.get("comparable",False) for x in out["matches"]),
      "wmo_only_fields":len(out["only_wmo"]),"ecmwf_only_fields":len(out["only_ecmwf"])}
    out["warnings"].append("المقارنة تصف الاختلاف بين المصدرين ولا تحكم بصحة التنبؤ؛ تقييم الدقة يحتاج رصداً مستقلاً.")
    return out

def main():
    p=argparse.ArgumentParser(description="مقارنة WMO مع ECMWF Open Data")
    p.add_argument("wmo_file",type=Path); p.add_argument("ecmwf_file",type=Path)
    p.add_argument("--output",type=Path,default=Path("output/source_comparison.json")); a=p.parse_args()
    report=compare_grib_files(a.wmo_file,a.ecmwf_file); a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
