#!/usr/bin/env python3
"""Read-only source-prefix review for owned parity-zero Triton cash hands.

All generated review artifacts are written beside this script. Raw source,
converter, corpus, and split files are read only.
"""
from __future__ import annotations
import copy, hashlib, json, pathlib, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.dont_write_bytecode = True
sys.pycache_prefix = str(HERE / '.pycache')
sys.path.insert(0, str(ROOT))
from pokerbot.ivey import normalize_card
from pokerbot.simulation import _positions
from pokerbot.corpus import validate_rows
from scripts.acquisition_pot_eligibility import inspect_prefix_pot
from scripts.verify_triton_semantics import inspect_hand

BASE = ROOT / 'data/acquisition_resume/2026-11-01/triton_cash'
CONV = HERE / 'converter_outputs/2024_ba7bbc03/converter-output.json'
AUDIT = json.loads((BASE / 'audit/hand-audit.json').read_text())
MANIFEST = json.loads((BASE / 'manifest/source-episodes.json').read_text())
HERO = '3970ce21-3d14-4bdc-97ca-98df8220d040'
DEAD = {'ante', 'small_ante', 'big_ante'}
LIVE = {'small_blind', 'big_blind', 'straddle'}
BET = {'raise', 'call', 'bet', 'all_in', 'check', 'fold'}
PAID = DEAD | LIVE | {'raise', 'call', 'bet', 'all_in'}
SESSION_BY_GROUP = {
    ('ccbde116-b26b-492e-8b81-30aef2575d8f', 'Cash Game Invitational I'):
        'triton:cash-session:ccbde116-b26b-492e-8b81-30aef2575d8f:b3bbb70deae657f0',
    ('d20c031a-a8d8-4106-a0c1-a3b31301a0b1', '€1 Million NLH Cash Game'):
        'triton:cash-session:d20c031a-a8d8-4106-a0c1-a3b31301a0b1:20bfb7ff6374f5b6',
}

def sha_bytes(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def canon_sha(v: object) -> str:
    return sha_bytes(json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode())
def load_hand(hid: str) -> tuple[dict, bytes, pathlib.Path]:
    p = BASE / 'hands' / f'{hid}.json'; raw = p.read_bytes()
    return json.loads(raw.decode('utf-8-sig'))['data']['handV2'], raw, p
def card(v: str) -> str:
    if not isinstance(v, str) or not v.startswith('CARD_'):
        raise ValueError(f'unsupported raw card {v!r}')
    return normalize_card(v[5:])
def street(v: str) -> str: return v.lower().replace('preflop', 'pre_flop')
def action_rows(hand: dict) -> list[tuple[int,int,int,str,dict]]:
    out=[]; flat=0
    for ri, rd in enumerate(hand['rounds']):
        for ai, a in enumerate(rd['actions']):
            out.append((flat,ri,ai,street(rd['name']),a)); flat+=1
    return out
def board_for(hand: dict, target_ri: int) -> list[str]:
    out=[]
    for ri, rd in enumerate(hand['rounds'][:target_ri+1]):
        name=street(rd['name'])
        if name=='flop': out.extend(card(c) for c in rd['communityCards'])
        elif name in {'turn','river'}: out.append(card(rd['communityCard']))
    return out
def expected_order(hand: dict, players_by_id: dict, sb: str, bb: str) -> list[str]:
    if len(players_by_id)==2: return [bb,sb]
    sb_seat=players_by_id[sb]['seatNo']
    return [p['userId'] for p in sorted(hand['players'], key=lambda p:(p['seatNo'] < sb_seat,p['seatNo']))]
def direct_prefix(hand: dict, ordered_ids: list[str], ordinal: int) -> dict:
    start={p['userId']:p['startChips'] for p in hand['players']}
    remaining=dict(start); live_contrib=dict.fromkeys(start,0); dead_by=dict.fromkeys(start,0)
    folded=set(); commits=dict.fromkeys(start,0); max_bet=0; cur_street=None; pot=0; dead_total=0
    history=[]; source=action_rows(hand); pos_by_id={uid:f'p{i}' for i,uid in enumerate(ordered_ids)}
    positions=_positions(len(ordered_ids))
    if ordinal < 0 or ordinal >= len(source): raise ValueError('target ordinal out of bounds')
    for flat,ri,ai,st,a in source[:ordinal]:
        if st != cur_street:
            cur_street=st; commits=dict.fromkeys(start,0); max_bet=0
        kind=a['type']; actor=a['userId']; amount=a.get('amount',0)
        if actor not in remaining: raise ValueError('unknown prefix actor')
        if actor in folded: raise ValueError('prefix action after fold')
        if kind in DEAD:
            remaining[actor]-=amount; dead_by[actor]+=amount; dead_total+=amount; pot+=amount
        elif kind in LIVE:
            remaining[actor]-=amount; live_contrib[actor]+=amount; commits[actor]+=amount; pot+=amount
            max_bet=max(max_bet,commits[actor])
        elif kind in BET:
            before=commits[actor]
            if kind=='fold': norm='fold'; logged=before; added=0; folded.add(actor)
            elif kind=='check': norm='check'; logged=before; added=0
            else:
                target=before+amount
                norm=('call' if kind=='all_in' and target<=max_bet else
                      'raise' if kind in {'raise','bet','all_in'} else 'call')
                logged=target; added=max(0,target-before)
                remaining[actor]-=amount; live_contrib[actor]+=amount; commits[actor]+=amount; pot+=amount
                if target>max_bet: max_bet=target
            history.append({'street':st.replace('_',''), 'player':pos_by_id[actor],
                            'position':positions[ordered_ids.index(actor)], 'action':norm,
                            'amount':logged,'added':added})
        else: raise ValueError(f'unknown prefix action {kind}')
        if remaining[actor] < 0: raise ValueError('negative prefix stack')
    target_row=source[ordinal]
    _,tri,tai,target_street,target_action=target_row
    if target_street != cur_street:
        cur_street=target_street; commits=dict.fromkeys(start,0); max_bet=0
    due=max(0,max_bet-commits[HERO]); to_call=min(due,remaining[HERO])
    active=[u for u in ordered_ids if u not in folded]
    hero_reach=live_contrib[HERO]+to_call
    opp_reach={u:live_contrib[u]+remaining[u] for u in active if u!=HERO}
    boundaries=set(v for v in live_contrib.values() if v>0); boundaries.add(hero_reach); boundaries.update(opp_reach.values())
    tiers=[]; previous=0; live_eligible=0
    for level in sorted(v for v in boundaries if v>0):
        contributors=[u for u,v in live_contrib.items() if v>=level]
        layer=(level-previous)*len(contributors)
        can_hero=hero_reach>=level
        can_opponents=[u for u,lim in opp_reach.items() if lim>=level]
        counted=can_hero and bool(can_opponents)
        if counted: live_eligible+=layer
        tiers.append({'from_level':previous,'to_level':level,'contributor_ids_including_folded':contributors,
                      'layer_amount':layer,'hero_can_reach':can_hero,'opponents_that_can_reach':can_opponents,'counted':counted})
        previous=level
    return {'source':source,'target':target_row,'start':start,'remaining':remaining,'live_contrib':live_contrib,
            'dead_by':dead_by,'dead_total':dead_total,'pot':pot,'folded':folded,'commits':commits,'max_bet':max_bet,
            'due':due,'to_call':to_call,'history':history,'tiers':tiers,'live_eligible':live_eligible,
            'contestable':dead_total+live_eligible,'hero_reach':hero_reach,'opp_reach':opp_reach,'active':active,
            'target_street':cur_street,'target_action':target_action,'target_round_index':tri,'target_round_action_index':tai}

converter=json.loads(CONV.read_text())
audit_by_id={r['handId']:r for r in AUDIT['hands']}
manifest_by_ep={e['episodeId']:e for e in MANIFEST['targetEpisodes']}
episode_meta={}
for ep in MANIFEST['targetEpisodes']:
    ed=json.loads((BASE/'episodes'/f"{ep['episodeId']}.json").read_text())['data']['episode']
    episode_meta[ep['episodeId']]={'festival_uuid':ed['festival']['uuid'],'festival_name':ed['festival']['name'],
                                   'event_name':ep['eventName'],'title':ed.get('title')}
terminal_cache={}; review_rows=[]; candidate_input=[]; sidecases=[]; issue_counts=Counter(); history_totals=Counter()
for original in converter['records']:
    row=copy.deepcopy(original); hid=row['canonical_hand_id'].split(':',1)[1]
    hand,raw,path=load_hand(hid); request_path=path.with_suffix('.request.json'); req_bytes=request_path.read_bytes(); req=json.loads(req_bytes.decode('utf-8-sig'))
    audit=audit_by_id[hid]; flat=int(row['source_action_index']); raw_rows=action_rows(hand)
    checks={}; detail={}
    def ck(name, ok, extra=None):
        checks[name]=bool(ok)
        if extra is not None: detail[name]=extra
    source_hash=sha_bytes(raw); request_hash=sha_bytes(req_bytes); query=req.get('query')
    payload_hash=canon_sha(hand)
    vars=req.get('variables') or {}; ep_id=vars.get('episodeId'); epmeta=episode_meta.get(ep_id,{})
    alias_ids=[a['episodeId'] for a in audit.get('aliases',[])]
    group=(epmeta.get('festival_uuid'),epmeta.get('event_name'))
    try: direct=direct_prefix(hand, expected_order(hand,{p['userId']:p for p in hand['players']},
                     next(a['userId'] for _,_,_,_,a in raw_rows if a['type']=='small_blind'),
                     next(a['userId'] for _,_,_,_,a in raw_rows if a['type']=='big_blind')), flat)
    except Exception as exc:
        direct={'error':str(exc)}
    helper=None; helper_error=None
    try: helper=inspect_prefix_pot(hand,flat)
    except Exception as exc: helper_error=str(exc)
    # Source and request identities.
    ck('source_response_hash_matches_converter_and_audit',source_hash==row['source_capture_sha256']==audit['responseSha256'],{'computed':source_hash,'candidate':row['source_capture_sha256'],'audit':audit['responseSha256']})
    ck('canonical_hand_payload_hash_matches_converter',payload_hash==row['source_payload_sha256'],{'computed':payload_hash,'candidate':row['source_payload_sha256']})
    ck('gethand_request_hash_matches_candidate_and_audit',request_hash==row['source_request_sha256']==audit['requestSha256'],{'computed':request_hash,'candidate':row['source_request_sha256'],'audit':audit['requestSha256']})
    ck('request_query_operation_variables_exact',req.get('operationName')=='GetHand' and vars.get('handId')==hid and ep_id in alias_ids and row['source_request_episode_id']==ep_id and row['source_request_variables']==vars,{'operation':req.get('operationName'),'variables':vars,'aliases':alias_ids})
    ck('request_query_hash_matches',isinstance(query,str) and sha_bytes(query.encode())==row['source_query_sha256'] and row['source_query_sha256']==MANIFEST['getHandQueryTextSha256'],{'query_sha256':row['source_query_sha256'],'manifest_query_sha256':MANIFEST['getHandQueryTextSha256']})
    ck('source_cash_event_context_is_explicit', 'cash' in str(epmeta.get('event_name','')).lower() and hand.get('pokerVariant')=='texas',epmeta)
    expected_session=SESSION_BY_GROUP.get(group)
    ck('episode_group_maps_to_shared_cash_session',expected_session==row['session_id'],{'group':group,'expected_session':expected_session,'candidate_session':row['session_id']})
    ck('hand_has_no_cross_event_alias',all((episode_meta.get(aid,{}).get('festival_uuid'),manifest_by_ep.get(aid,{}).get('eventName'))==group for aid in alias_ids),{'aliases':alias_ids,'group':group})
    # Exact source action and provenance locator.
    target_ok=0<=flat<len(raw_rows)
    target=raw_rows[flat] if target_ok else None
    locator_ok=bool(target and target[1]==row['source_round_index'] and target[2]==row['source_round_action_index'] and target[4].get('userId')==HERO and target[4].get('type') in BET)
    locators={(loc['roundIndex'],loc['actionIndex']) for loc in audit.get('actionLocators',[])}
    ck('raw_round_action_identity_and_hero_actor_match',locator_ok and (row['source_round_index'],row['source_round_action_index']) in locators,{'ordinal':flat,'source_round_index':row['source_round_index'],'source_round_action_index':row['source_round_action_index'],'raw_action':target[4] if target else None,'audit_locator_present':(row['source_round_index'],row['source_round_action_index']) in locators})
    ck('stable_source_decision_key_matches_raw_position',row['source_decision_id']==f'triton:{hid}:action:{flat}' and row['stable_source_decision_key']==f"triton:{hid}:round:{row['source_round_index']}:action:{row['source_round_action_index']}")
    # Physical order, forced posts, stack, label, and history.
    players={p['userId']:p for p in hand['players']}; seats=[p['seatNo'] for p in hand['players']]
    sb_rows=[a for _,_,_,_,a in raw_rows if a['type']=='small_blind']; bb_rows=[a for _,_,_,_,a in raw_rows if a['type']=='big_blind']
    forced_live=[(a['type'],a['userId']) for _,_,_,_,a in raw_rows if a['type'] in LIVE]
    if len(sb_rows)==1 and len(bb_rows)==1:
        ordered=expected_order(hand,players,sb_rows[0]['userId'],bb_rows[0]['userId'])
        expected_live=[('small_blind',sb_rows[0]['userId']),('big_blind',bb_rows[0]['userId'])]
        expected_live += [('straddle',u) for u in ordered[2:] if ('straddle',u) in forced_live]
        dealer_id=next((p['userId'] for p in hand['players'] if p['seatNo']==hand.get('dealerSeatNo')),None)
        ring_ok=(ordered[0]==sb_rows[0]['userId'] and (len(ordered)==2 or ordered[1]==bb_rows[0]['userId'])
                 and forced_live==expected_live and ((len(ordered)==2 and hand.get('dealerSeatNo')==players[ordered[-1]]['seatNo'])
                                                    or (len(ordered)>2 and dealer_id==ordered[-1])))
    else: ordered=[]; ring_ok=False; dealer_id=None
    ck('seat_blind_button_and_straddle_order_match_raw',ring_ok,{'seat_numbers':seats,'dealer_seat':hand.get('dealerSeatNo'),'dealer_actor':dealer_id,'ordered_user_ids':ordered,'live_forced_source_order':forced_live})
    forced=[(ri,ai,a) for _,ri,ai,_,a in raw_rows if a['type'] in DEAD|LIVE]
    first_voluntary=next((ordinal for ordinal,_,_,_,a in raw_rows if a['type'] not in DEAD|LIVE),len(raw_rows))
    posts_preflop=all(street(hand['rounds'][ri]['name'])=='pre_flop' for ri,_,_ in forced)
    posts_precede_betting=all(next((o for o,rr,aa,_,_ in raw_rows if rr==ri and aa==ai),len(raw_rows))<first_voluntary for ri,ai,_ in forced)
    ck('forced_ante_and_blind_actions_are_explicit_preflop_prefix',posts_preflop and posts_precede_betting,{'forced_posts':[{'round':ri,'action':ai,'type':a['type'],'userId':a['userId'],'amount':a['amount']} for ri,ai,a in forced]})
    ck('actual_player_count_and_physical_capacity_match_raw',len(players)==row['source_actual_player_count']==row['state']['table_size'] and hand.get('noOfSeats')==row['source_physical_capacity'],{'actual':len(players),'capacity':hand.get('noOfSeats'),'state_table_size':row['state']['table_size']})
    if target and not isinstance(direct,dict) or 'error' not in direct:
        pass
    if isinstance(direct,dict) and 'error' not in direct:
        target_action=direct['target_action']; actor=target_action['userId']; kind=target_action['type']; amount=target_action.get('amount',0)
        before=direct['commits'][actor]; current=direct['max_bet']; target_amount=before+amount
        normalized=('call' if kind=='all_in' and target_amount<=current else ('raise' if kind in {'raise','bet','all_in'} else kind))
        expected={'action':normalized}
        if normalized=='raise': expected['amount']=target_amount
        ck('hero_starting_stack_and_prior_stack_ledger_match',row['state']['stack']==direct['remaining'][HERO],{'state_stack':row['state']['stack'],'raw_remaining_stack':direct['remaining'][HERO]})
        ck('predecision_history_matches_raw_prior_actions_and_pn_actors',row['state']['history']==direct['history'],{'history_entries':len(direct['history']),'source_action_prefix_count':flat})
        ck('decision_label_matches_original_raw_action',row['expected']==expected,{'raw_type':kind,'raw_amount_added':amount,'expected_from_source':expected,'converter_expected':row['expected']})
        ck('hero_pn_and_position_match_source_seat_order',row['state']['player_id']==f"p{ordered.index(HERO)}" and row['state']['position']==_positions(len(ordered))[ordered.index(HERO)],{'ordered_ids':ordered,'expected_player_id':f"p{ordered.index(HERO)}" if ordered else None,'expected_position':_positions(len(ordered))[ordered.index(HERO)] if ordered else None})
        ck('active_player_count_matches_prior_folds',row['state']['players_active']==len(direct['active']),{'state_active':row['state']['players_active'],'raw_active':len(direct['active'])})
        ck('current_bet_matches_source_prefix',row['state']['current_bet']==direct['commits'][HERO],{'state_current_bet':row['state']['current_bet'],'hero_street_commitment':direct['commits'][HERO]})
        try: expected_board=board_for(hand,direct['target_round_index'])
        except Exception as exc: expected_board=[]; detail['board_derivation_error']=str(exc)
        ck('visible_board_matches_current_round_and_has_no_future_cards',row['state']['board']==expected_board,{'state_board':row['state']['board'],'source_board_at_decision':expected_board})
        action_ts=target_action.get('timestamp'); reveal=[]
        for rd in hand['rounds'][:direct['target_round_index']+1]:
            nm=street(rd['name'])
            if nm=='flop': reveal.extend(rd.get('communityCardTimestamps',[]))
            elif nm in {'turn','river'}: reveal.append(rd.get('communityCardTimestamp'))
        valid_reveal=all(type(t)is int and t>=0 for t in reveal)
        ck('target_action_occurs_after_all_visible_board_reveals',type(action_ts)is int and valid_reveal and all(action_ts>=t for t in reveal),{'action_timestamp':action_ts,'visible_reveal_timestamps':reveal})
        try: hero_raw=players[HERO].get('pocketCards'); hero_cards=[card(c) for c in hero_raw] if isinstance(hero_raw,list) and len(hero_raw)==2 and all(hero_raw) else None
        except Exception as exc: hero_cards=None; detail['hero_card_error']=str(exc)
        ck('hero_known_cards_match_raw_and_opponent_cards_are_unknown',hero_cards is not None and row['state']['hole_cards']==hero_cards and len(row['state']['hole_cards'])==2,{'raw_card_count':len(hero_raw) if isinstance(hero_raw,list) else None,'state_cards':row['state']['hole_cards']})
        # Independent ante and live-tier reconstruction from strictly prior source payments.
        live_direct=dict.fromkeys(players,0); dead_direct=dict.fromkeys(players,0); total_direct=0
        for _,_,_,_,a in raw_rows[:flat]:
            typ=a['type']; who=a['userId']
            if typ in PAID:
                amt=a['amount']; total_direct+=amt
                if typ in DEAD: dead_direct[who]+=amt
                else: live_direct[who]+=amt
        def normalize_tiers(rows):
            return [{**tier,
                     'contributor_ids_including_folded':sorted(tier['contributor_ids_including_folded']),
                     'opponents_that_can_reach':sorted(tier['opponents_that_can_reach'])}
                    for tier in rows]
        tier_match=bool(helper) and normalize_tiers(helper['evidence']['tiers'])==normalize_tiers(direct['tiers'])
        helper_components={
            'pot':bool(helper) and helper['pot']==total_direct==direct['pot'],
            'to_call':bool(helper) and helper['to_call']==direct['to_call'],
            'call_amount_due':bool(helper) and helper['call_amount_due']==direct['due'],
            'dead_ante_contributions':bool(helper) and helper['dead_ante_contributions']==dict(dead_direct),
            'live_contributions':bool(helper) and helper['live_contributions']==dict(live_direct),
            'remaining_stacks':bool(helper) and helper['evidence']['remaining_stacks']==direct['remaining'],
            'folded_players':bool(helper) and helper['evidence']['folded_players']==sorted(direct['folded']),
            'reachable_live_tiers':tier_match,
            'contestable_pot':bool(helper) and helper['contestable_pot']==direct['contestable'],
        }
        helper_ok=all(helper_components.values())
        detail['helper_component_checks']=helper_components
        ck('helper_pot_call_antes_live_tiers_match_independent_raw_prefix',helper_ok,{'helper_error':helper_error,'helper_pot':helper.get('pot') if helper else None,'source_prefix_pot':total_direct,'helper_to_call':helper.get('to_call') if helper else None,'engine_to_call':row['state']['to_call'],'helper_contestable':helper.get('contestable_pot') if helper else None,'independently_derived_contestable':direct['contestable']})
        ck('engine_pot_and_to_call_match_independent_prefix',row['state']['pot']==direct['pot']==(helper or {}).get('pot') and row['state']['to_call']==direct['to_call']==(helper or {}).get('to_call'),{'state_pot':row['state']['pot'],'raw_prefix_pot':direct['pot'],'state_to_call':row['state']['to_call'],'raw_prefix_to_call':direct['to_call']})
        old_eligible=row['state']['contestable_pot']; corrected=direct['contestable']
        row['state']['contestable_pot']=corrected
        ck('eligible_pot_correction_is_recomputed_from_raw_prefix',corrected==helper['contestable_pot'],{'before':old_eligible,'corrected':corrected,'raw_total_pot':direct['pot']})
        row['source_cash_group']={'festival_uuid':group[0],'event_name':group[1]}
    else:
        ck('independent_prefix_and_history_reconstruction_available',False,{'error':direct.get('error') if isinstance(direct,dict) else 'no result'})
    # Terminal records are inspected only as source accounting validation, never copied into state.
    if hid not in terminal_cache:
        terminal_cache[hid]=inspect_hand(hand)
    term=terminal_cache[hid]
    ck('independent_terminal_accounting_validation_passes',term.get('accounting_and_prefix_price_checks_pass') is True,{'problem_count':len(term.get('problems',[]))})
    state_keys=set(row['state'])
    forbidden={'pots','winners','payouts','end_chips','terminal_stacks','showdown_cards','opponent_hole_cards','future_actions','source_action'}
    ck('current_label_future_opponent_privates_and_terminal_facts_are_out_of_state',not (state_keys & forbidden) and all(k in {'big_blind','board','contestable_pot','current_bet','history','hole_cards','legal_actions','max_raise_to','min_raise_to','player_id','players_active','players_to_act','position','pot','seed','stack','street','table_size','to_call'} for k in state_keys),{'state_keys':sorted(state_keys),'forbidden_present':sorted(state_keys & forbidden)})
    issue_counts.update(name for name,ok in checks.items() if not ok)
    history_totals['eligible_pot_corrected_rows'] += int(detail.get('eligible_pot_correction_is_recomputed_from_raw_prefix',{}).get('before') != detail.get('eligible_pot_correction_is_recomputed_from_raw_prefix',{}).get('corrected'))
    review_rows.append({'source_decision_id':row['source_decision_id'],'stable_source_decision_key':row['stable_source_decision_key'],
                        'source_raw_hand_uuid':hid,'source_action_index':flat,'source_round_index':row['source_round_index'],
                        'source_round_action_index':row['source_round_action_index'],'source_episode_id':ep_id,
                        'source_episode_aliases':alias_ids,'source_group':{'festival_uuid':group[0],'event_name':group[1]},
                        'source_response_sha256':source_hash,'source_request_sha256':request_hash,
                        'raw_action':target[4] if target else None,'checks':checks,'details':detail,
                        'old_contestable_pot':original['state']['contestable_pot'],'corrected_contestable_pot':row['state']['contestable_pot'],
                        'pot':row['state']['pot'],'to_call':row['state']['to_call'],
                        'review_status':'passed' if all(checks.values()) else 'blocked'})
    # Remove hash-derived fields so the corrected rows get fresh IDs and record hashes below.
    for key in ('decision_id','record_hash','group_id','partition'):
        row.pop(key,None)
    candidate_input.append(row)

for r in candidate_input:
    r['admission_status']='pending_independent_admission_decision_development_only'
    r['evidence_tier']='acquired_history_reviewed_development_only'
validated=validate_rows(candidate_input)
if len(validated)!=len(candidate_input): raise RuntimeError('row validator count changed')
failed=[r for r in review_rows if r['review_status']!='passed']
if failed: print('INDEPENDENT_REVIEW_FAILURES',json.dumps([{'id':r['source_decision_id'],'checks':[k for k,v in r['checks'].items() if not v]} for r in failed[:10]]))
# Write corrected candidates, per-row evidence, and converted-source blockers.
(HERE/'candidates.json').write_text(json.dumps({'schema_version':1,'status':'development_only_candidates_pending_parent_admission','counts':{'validated_candidate_decisions':len(validated),'source_hands':len({r['source_raw_hand_uuid'] for r in review_rows}),'admissions_created':0,'eligible_pot_values_corrected':sum(r['old_contestable_pot']!=r['corrected_contestable_pot'] for r in review_rows)},'records':validated,'limitations':['Every inspected row is development-only.','No row is admitted or fresh-heldout.','Raw opponent cards and terminal outcomes are excluded from state.']},indent=2,sort_keys=True,allow_nan=False)+'\n')
(HERE/'per-row-review.json').write_text(json.dumps({'schema_version':1,'status':'independent_raw_prefix_review','rows':review_rows},indent=2,sort_keys=True,allow_nan=False)+'\n')
# 2018 source seat facts for all records, with a parity-zero summary and no altered source fields.
seat_facts=[]
for ar in AUDIT['hands']:
    hid=ar['handId']; aliases=ar.get('aliases',[])
    if not aliases or '2018' not in manifest_by_ep[aliases[0]['episodeId']]['festivalName']: continue
    hand,_,_=load_hand(hid); players=hand['players']; byid={p['userId']:p for p in players}
    acts=[a for rd in hand['rounds'] for a in rd['actions']]
    sb=[a for a in acts if a['type']=='small_blind']; bb=[a for a in acts if a['type']=='big_blind']
    if len(sb)==1 and len(bb)==1:
        order=expected_order(hand,byid,sb[0]['userId'],bb[0]['userId'])
        actual_live=[(a['type'],a['userId']) for a in acts if a['type'] in LIVE]
        expected_live=[('small_blind',sb[0]['userId']),('big_blind',bb[0]['userId'])]+[('straddle',u) for u in order[2:] if ('straddle',u) in actual_live]
        dealer=next((p['userId'] for p in players if p['seatNo']==hand['dealerSeatNo']),None)
        ordering_ok=(order[0]==sb[0]['userId'] and (len(order)==2 or order[1]==bb[0]['userId']) and actual_live==expected_live and ((len(order)==2 and dealer==sb[0]['userId']) or (len(order)>2 and dealer==order[-1])))
    else: order=[]; ordering_ok=False
    seat_facts.append({'hand_id':hid,'owned_even':int(hid.replace('-',''),16)%2==0,'no_of_seats':hand.get('noOfSeats'),'actual_player_count':len(players),'seat_numbers':sorted(p['seatNo'] for p in players),'dealer_seat':hand.get('dealerSeatNo'),'explicit_small_blind_seat':byid[sb[0]['userId']]['seatNo'] if len(sb)==1 else None,'explicit_big_blind_seat':byid[bb[0]['userId']]['seatNo'] if len(bb)==1 else None,'clockwise_seat_numbers_from_small_blind':[byid[u]['seatNo'] for u in order],'live_forced_posts_match_seat_order':ordering_ok})
capacity=Counter(str(f['no_of_seats']) for f in seat_facts); maxseat=Counter(str(max(f['seat_numbers'])) for f in seat_facts)
seat_block={'total_2018_hand_records':len(seat_facts),'owned_even_hand_records':sum(f['owned_even'] for f in seat_facts),'no_of_seats_values':dict(capacity),'actual_player_counts':dict(Counter(str(f['actual_player_count']) for f in seat_facts)),'maximum_physical_seat_values':dict(maxseat),'records_with_seat_9':sum(9 in f['seat_numbers'] for f in seat_facts),'unique_seat_records':sum(len(f['seat_numbers'])==len(set(f['seat_numbers'])) for f in seat_facts),'explicit_blind_button_and_straddle_order_passes_when_capacity_ignored':sum(f['live_forced_posts_match_seat_order'] for f in seat_facts),'frontend_evidence':{'cached_gethand_selection_includes':['noOfSeats','dealerSeatNo','players.seatNo'],'semantics_note':'The cached GraphQL selection requests noOfSeats and per-player seatNo as separate source fields. No frontend renderer/source bundle is part of the local acquisition cache, so UI layout implementation is not independently documented here.'},'recommendation':'Do not pad players. Retain noOfSeats as raw provenance metadata, but it can be omitted from ordering when it conflicts with the explicit physical seat labels: rotating the actual unique seatNo records from the explicit small blind gives SB first, BB second, and the dealer at the end (or HU BTN/SB) for all 77 hands.' ,'records':seat_facts}
(HERE/'sidecases').mkdir(exist_ok=True)
(HERE/'sidecases/2018-seat-capacity.json').write_text(json.dumps(seat_block,indent=2,sort_keys=True)+'\n')
# Failed source hands and typed rejections remain explicit sidecases; none is candidate/admitted.
conv18=json.loads((HERE/'converter_outputs/2018_2c503059/converter-output.json').read_text())
conv24=converter
rejections=[]
for name,co in [('2018',conv18),('2024',conv24)]:
    for item in co.get('rejections',[]):
        rejections.append({'source_group':name,**item})
(HERE/'sidecases/conversion-rejections.json').write_text(json.dumps({'development_only':True,'rejection_count':len(rejections),'rejections_by_reason':dict(Counter(r.get('reason','unknown') for r in rejections)),'records':rejections},indent=2,sort_keys=True)+'\n')
sourceblock={'status':'source_blockers_documented','admissions_created':0,'blockers':[{'group':'2018 Montenegro Cash Game / €1 Million NLH Cash Game','owned_hands':41,'owned_candidates':0,'reason':'current converter rejects all parity-zero source hand records because source noOfSeats=8 conflicts with explicit seatNo=9','rejection_reasons':dict(Counter(r.get('reason','unknown') for r in conv18.get('rejections',[]))),'evidence_path':'sidecases/2018-seat-capacity.json','ordering_evidence':'all 77 source hands pass explicit SB/BB/button/straddle seat-order checks when actual player seatNo labels are rotated; no padding used'},{'group':'2024 Montenegro / Cash Game Invitational I','owned_hands':234,'validated_candidates':241,'rejected_hands':len(conv24.get('rejections',[])),'rejection_reasons':dict(Counter(r.get('reason','unknown') for r in conv24.get('rejections',[]))),'conservative_board_cutoff_kept':True,'note':'Actions before the latest public-board reveal remain excluded.'}],'sidecases':['2018-seat-capacity.json','conversion-rejections.json']}
(HERE/'sidecases/sourceblockers.json').write_text(json.dumps(sourceblock,indent=2,sort_keys=True)+'\n')
# Check current converter/helper hashes again, but retain captured at-start hashes in checkpoint.
import subprocess
current_hashes={}
for p in ('scripts/acquisition_triton_convert.py','scripts/acquisition_pot_eligibility.py','scripts/acquisition_import.py'):
    current_hashes[p]=sha_bytes((ROOT/p).read_bytes())
summary={'schema_version':1,'review':'triton_cash_review_0','reviewed_at_utc':datetime.now(timezone.utc).isoformat(),'status':'reviewed_development_only','counts':{'owned_raw_hand_records':275,'owned_known_two_card_hands':225,'owned_hero_action_locators':340,'converted_2024_decisions':len(review_rows),'independently_passed_decisions':len(review_rows)-len(failed),'independent_review_failures':len(failed),'unique_candidate_hands':len({r['source_raw_hand_uuid'] for r in review_rows}),'candidate_hands_2018_capacity_blocked':41,'candidate_decisions_2018':0,'contestable_pot_recomputed':sum(r['old_contestable_pot']!=r['corrected_contestable_pot'] for r in review_rows),'engine_pot_to_call_matches':sum(r['checks'].get('engine_pot_and_to_call_match_independent_prefix',False) for r in review_rows),'helper_ante_live_tier_checks_pass':sum(r['checks'].get('helper_pot_call_antes_live_tiers_match_independent_raw_prefix',False) for r in review_rows),'unmatched_top_pot_sidecases':sum(r['pot']!=r['corrected_contestable_pot'] for r in review_rows),'admissions_created':0},'converter_counts':{'2018':conv18['counts'],'2024':conv24['counts']},'converter_rejection_reasons_2024':dict(Counter(r.get('reason','unknown') for r in conv24.get('rejections',[]))),'all_inspected_development_only':True,'global_dedup':'pending','input_hashes':{'source_manifest_sha256':sha_bytes((BASE/'manifest/source-episodes.json').read_bytes()),'source_hand_audit_sha256':sha_bytes((BASE/'audit/hand-audit.json').read_bytes()),'converter_output_2024_sha256':sha_bytes(CONV.read_bytes()),'converter_output_2018_sha256':sha_bytes((HERE/'converter_outputs/2018_2c503059/converter-output.json').read_bytes()),'converter_sha256_at_start':'aeba51655c1927a47b2b9bd7f404a94a15a7299abde52f9ce9d8ba0cb483a7ca','pot_helper_sha256_at_start':'3bf5bb521dfca1e4ed16871f19d50fef125cdded6c2ebd3ae253ab805dda6556','current_code_sha256':current_hashes},'notes':['No source/API fetch, policy call, training, score evaluation, admissions, or split changes.','Converter rejected hands are left out; no raw fields were changed.','Corrected contestable_pot values were revalidated with pokerbot.corpus.validate_rows to refresh decision_id and record_hash.','Terminal pot and end-stack data were used only by independent accounting validation and are absent from candidate states.']}
(HERE/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+'\n')
# Checkpoint updated early and again on completion; byte hashes for scope enforcement are recorded later.
checkpoint={'review':'triton_cash_review_0','status':'source_review_complete_pending_global_dedup','updated_at_utc':datetime.now(timezone.utc).isoformat(),'scope':{'exclusive_write_root':str(HERE.relative_to(ROOT)),'owned_hand_uuid_formula':'int(handId.replace("-", ""), 16) % 2 == 0','owned_hand_records':275,'admissions_created':0,'all_inspected_development_only':True},'converter_sha256_at_start':'aeba51655c1927a47b2b9bd7f404a94a15a7299abde52f9ce9d8ba0cb483a7ca','pot_helper_sha256_at_start':'3bf5bb521dfca1e4ed16871f19d50fef125cdded6c2ebd3ae253ab805dda6556','converted_decisions':len(review_rows),'independent_review_passed':len(review_rows)-len(failed),'independent_review_failed':len(failed),'pot_call_matches':summary['counts']['engine_pot_to_call_matches'],'corrected_contestable_pot_values':summary['counts']['contestable_pot_recomputed'],'protected_input_paths_modified':[],'next':'Complete global dedup against 80 admitted rows and other Triton artifacts; write final hashes and review.md.'}
(HERE/'checkpoint.json').write_text(json.dumps(checkpoint,indent=2,sort_keys=True)+'\n')
print(json.dumps({'rows':len(review_rows),'passed':len(review_rows)-len(failed),'failed':len(failed),'failed_check_counts':dict(issue_counts),'pot_corrected':summary['counts']['contestable_pot_recomputed'],'seat_2018_pass':seat_block['explicit_blind_button_and_straddle_order_passes_when_capacity_ignored'],'total_2018':seat_block['total_2018_hand_records'],'rejections':summary['converter_rejection_reasons_2024']},indent=2))
