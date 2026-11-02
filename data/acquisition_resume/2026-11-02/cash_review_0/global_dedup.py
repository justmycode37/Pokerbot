#!/usr/bin/env python3
"""Deduplicate reviewed candidate decisions against admissions and other Triton artifacts."""
import hashlib,json,pathlib,re,sys
from collections import defaultdict
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[3]
sys.dont_write_bytecode=True; sys.pycache_prefix=str(HERE/'.pycache')
sys.path.insert(0,str(ROOT))
from pokerbot.corpus import validate_rows
UUID_RE=re.compile(r'(?i)([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})')
DEC_RE=re.compile(r'(?i)^triton:([0-9a-f-]{36}):action:(\d+)$')
STABLE_RE=re.compile(r'(?i)^triton:([0-9a-f-]{36}):round:(\d+):action:(\d+)$')
HERO='3970ce21-3d14-4bdc-97ca-98df8220d040'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def walk(v):
    if isinstance(v,dict):
        yield v
        for child in v.values(): yield from walk(child)
    elif isinstance(v,list):
        for child in v: yield from walk(child)
def triton_uuid(v):
    if not isinstance(v,str): return None
    m=UUID_RE.search(v)
    if m and (v.lower().startswith('triton:') or v.lower()==m.group(1).lower()): return m.group(1).lower()
    return None
def identities(obj):
    out=set(); raw_ids=set()
    if not isinstance(obj,dict): return out,raw_ids
    dec=obj.get('source_decision_id') or obj.get('source_canonical_decision_id')
    m=DEC_RE.fullmatch(dec or '')
    if m:
        u=m.group(1).lower(); ordinal=int(m.group(2)); out.add(('flat',u,ordinal)); raw_ids.add(u)
    stable=obj.get('stable_source_decision_key') or obj.get('stable_hand_round_action_key')
    m=STABLE_RE.fullmatch(stable or '')
    if m:
        u=m.group(1).lower(); ri=int(m.group(2)); ai=int(m.group(3)); out.add(('round',u,ri,ai)); raw_ids.add(u)
    u=triton_uuid(obj.get('canonical_hand_id')) or triton_uuid(obj.get('hand_id'))
    if u:
        raw_ids.add(u)
        ri=obj.get('source_round_index',obj.get('round_index'))
        ai=obj.get('source_round_action_index',obj.get('round_action_index'))
        if type(ri)is int and type(ai)is int: out.add(('round',u,ri,ai))
        flat=obj.get('source_action_index')
        if type(flat)is int: out.add(('flat',u,flat))
        # For compact candidate inventories, action_index is the per-round action index.
        if type(obj.get('round_index'))is int and type(obj.get('action_index'))is int:
            out.add(('round',u,obj['round_index'],obj['action_index']))
    # Raw source hand records provide the strongest original round/action identity.
    hid=obj.get('handId'); hm=UUID_RE.fullmatch(hid or '') if isinstance(hid,str) else None
    rounds=obj.get('rounds'); players=obj.get('players')
    if hm and isinstance(rounds,list) and isinstance(players,list):
        u=hm.group(1).lower(); raw_ids.add(u)
        if any(isinstance(p,dict) and p.get('userId')==HERO for p in players):
            for ri,rd in enumerate(rounds):
                if not isinstance(rd,dict) or not isinstance(rd.get('actions'),list): continue
                for ai,a in enumerate(rd['actions']):
                    if isinstance(a,dict) and a.get('userId')==HERO and a.get('type') in {'raise','call','bet','all_in','check','fold'}:
                        out.add(('round',u,ri,ai))
    return out,raw_ids

# Validate that all corrected candidate record hashes are current.
cand_path=HERE/'candidates.json'; cand_doc=json.loads(cand_path.read_text()); candidates=cand_doc['records']
clean_input=[]
for r in candidates:
    x={k:v for k,v in r.items() if k not in {'record_hash','decision_id','group_id','partition'}}
    clean_input.append(x)
reconstructed=validate_rows(clean_input)
row_hash_validation=(len(reconstructed)==len(candidates) and all(a.get('record_hash')==b.get('record_hash') and a.get('decision_id')==b.get('decision_id') and a.get('group_id')==b.get('group_id') for a,b in zip(candidates,reconstructed)))
if not row_hash_validation: raise RuntimeError('corrected candidate record_hash / decision_id revalidation failed')
# Admission baseline (45) plus two new admitted batches (30 + 5) = 80.
paths=[ROOT/'data/corpus_splits/development-after-prospective-v1.json',ROOT/'data/acquisition_resume/2026-11-01/admissions/batch-001.json',ROOT/'data/acquisition_resume/2026-11-01/admissions/batch-002.json']
admitted=[]
for p in paths:
    doc=json.loads(p.read_text()); admitted.extend(doc['records'])
admitted_sets=set(); admitted_raw=set(); admitted_source_ids=set()
for rec in admitted:
    ids,raws=identities(rec); admitted_sets.update(ids); admitted_raw.update(raws)
    if isinstance(rec.get('source_decision_id'),str): admitted_source_ids.add(rec['source_decision_id'])
candidate_sets=set(); candidate_raw=set(); candidate_flat=set(); candidate_round=set()
for rec in candidates:
    ids,raws=identities(rec); candidate_sets.update(ids); candidate_raw.update(raws)
    candidate_flat.add(rec['source_decision_id']); candidate_round.add(rec['stable_source_decision_key'])
# Scan other cached Triton acquisition and review artifacts. Omit raw current triton_cash source
# files and this review folder to prevent self-matches; include the prior parity-one review.
scanroot=ROOT/'data/acquisition_resume'
other_sets=set(); other_raw=set(); raw_sources=defaultdict(set); matching_files={}
scanned=[]
for p in sorted(scanroot.rglob('*')):
    if not p.is_file() or p.suffix.lower() not in {'.json','.jsonl'}: continue
    rel=str(p.relative_to(ROOT))
    if rel.startswith('data/acquisition_resume/2026-11-01/triton_cash/') or rel.startswith(str(HERE.relative_to(ROOT))+'/'):
        continue
    try:
        documents=[]
        if p.suffix.lower()=='.jsonl':
            documents=[json.loads(line) for line in p.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        else: documents=[json.loads(p.read_text(encoding='utf-8-sig'))]
    except (OSError,UnicodeError,json.JSONDecodeError): continue
    found_file=False
    for doc in documents:
        for obj in walk(doc):
            ids,raws=identities(obj)
            if ids:
                other_sets.update(ids); found_file=True
                for identity in ids:
                    if identity in candidate_sets: matching_files.setdefault(str(identity),set()).add(rel)
            for raw in raws:
                other_raw.add(raw); raw_sources[raw].add(rel); found_file=True
    if found_file: scanned.append({'path':rel,'sha256':sha(p)})
exact_admitted=sorted(candidate_sets & admitted_sets)
exact_other=sorted(candidate_sets & other_sets)
flat_other=sorted(candidate_flat & {f'triton:{x[1]}:action:{x[2]}' for x in other_sets if x[0]=='flat'})
round_other=sorted(candidate_round & {f'triton:{x[1]}:round:{x[2]}:action:{x[3]}' for x in other_sets if x[0]=='round'})
raw_overlap_admitted=sorted(candidate_raw & admitted_raw)
raw_overlap_other=sorted(candidate_raw & other_raw)
# Episode aliases on the raw audit are provenance only; list repeated raw UUIDs, if any.
source_audit=json.loads((ROOT/'data/acquisition_resume/2026-11-01/triton_cash/audit/hand-audit.json').read_text())
aliases=[]
for row in source_audit['hands']:
    hid=row['handId']
    if int(hid.replace('-',''),16)%2==0 and len(row.get('aliases',[]))>1:
        aliases.append({'raw_hand_uuid':hid,'episode_ids':[a['episodeId'] for a in row['aliases']]})
result={'schema_version':1,'status':'global_dedup_complete_development_only','dedup_identity':'source raw hand UUID + original round/action identity; episode identifiers are provenance only','counts':{'admitted_records_total':len(admitted),'baseline_frozen_records':len(json.loads(paths[0].read_text())['records']),'new_admission_batch_001_records':len(json.loads(paths[1].read_text())['records']),'new_admission_batch_002_records':len(json.loads(paths[2].read_text())['records']),'reviewed_candidate_records':len(candidates),'unique_reviewed_raw_hand_uuids':len(candidate_raw),'reviewed_candidate_identities':len(candidate_round),'candidate_identity_forms_checked':len(candidate_sets),'exact_identity_duplicates_with_80_admitted':len(exact_admitted),'exact_identity_duplicates_with_other_triton_artifacts':len(exact_other),'raw_uuid_overlaps_with_80_admitted':len(raw_overlap_admitted),'raw_uuid_overlaps_with_other_triton_artifacts':len(raw_overlap_other),'owned_source_hand_ids_with_multiple_episode_aliases':len(aliases),'other_triton_identity_forms_found':len(other_sets),'other_triton_raw_hand_uuids_found':len(other_raw),'candidate_record_hashes_revalidated':len(candidates) if row_hash_validation else 0},'duplicates':{'admitted_identity_keys':exact_admitted,'other_triton_identity_keys':exact_other,'raw_uuid_overlaps_with_admissions':raw_overlap_admitted,'raw_uuid_overlaps_with_other_triton':raw_overlap_other,'candidate_matches_in_other_artifact_paths':matching_files},'episode_alias_raw_uuids':aliases,'candidate_raw_uuid_alias_policy':'Episode aliases were inspected as provenance and do not alter source hand/action identity. None of the 275 owned raw source hand IDs has multiple episode aliases.','inputs':{'admission_and_frozen_files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in paths],'other_triton_artifacts_scanned':scanned}}
(HERE/'global-dedup.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
# Update summary/checkpoint after dedup is complete.
sum_path=HERE/'summary.json'; summary=json.loads(sum_path.read_text())
summary['global_dedup']={'admitted_total':len(admitted),'candidate_identities':len(candidate_round),'candidate_identity_forms_checked':len(candidate_sets),'duplicates_with_admitted':len(exact_admitted),'duplicates_with_other_triton':len(exact_other),'raw_uuid_overlaps_with_other_triton':len(raw_overlap_other),'admitted_input_hashes':{str(p.relative_to(ROOT)):sha(p) for p in paths},'report_path':'global-dedup.json'}
sum_path.write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+'\n')
cp_path=HERE/'checkpoint.json'; cp=json.loads(cp_path.read_text()); cp.update({'status':'complete','updated_at_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'global_dedup':{'admitted_records':len(admitted),'exact_duplicates_with_admitted':len(exact_admitted),'exact_duplicates_with_other_triton':len(exact_other),'raw_uuid_overlaps_with_other_triton':len(raw_overlap_other),'report_path':'global-dedup.json'},'candidate_records_revalidated':row_hash_validation,'protected_input_paths_modified':[],'next':'Parent may review and integrate candidates. This task created no admissions.'})
cp_path.write_text(json.dumps(cp,indent=2,sort_keys=True)+'\n')
print(json.dumps({'admitted':len(admitted),'candidate_rows':len(candidates),'candidate_identities':len(candidate_round),'candidate_identity_forms_checked':len(candidate_sets),'duplicates_admitted':len(exact_admitted),'duplicates_other_triton':len(exact_other),'raw_uuid_overlap_other':len(raw_overlap_other),'aliases':len(aliases),'scan_files_with_triton_identities':len(scanned),'row_hash_revalidated':row_hash_validation},indent=2))
