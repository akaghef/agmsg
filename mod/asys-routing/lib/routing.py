#!/usr/bin/env python3
"""Mac-local agmsg Bridge adapter. No packet is moved or deleted."""
import argparse, datetime as dt, hashlib, json, os, pathlib, shutil, subprocess, sys, time
import re

ROOT = pathlib.Path(os.environ.get("AGMSG_BRIDGE_ROOT", pathlib.Path.home()/"Akaghef-Bridge"))
STATE = pathlib.Path(os.environ.get("AGMSG_STATE_DIR", pathlib.Path.home()/".local/share/akaghef-system/agmsg"))
LAYER = pathlib.Path(os.environ.get("AGMSG_ROUTING_ROOT", pathlib.Path(__file__).resolve().parents[1]))
DEVICES={"mac":"mac","win":"win","windows":"win","dell":"win","mini":"mini"}
TEAMS={"akaghef-system":"a-sys","system":"a-sys"}

def parse(raw):
    realm, sep, address = raw.partition(":")
    if not sep: realm,address="local",raw
    if not realm or "/" not in address: raise ValueError("address must be [realm:]team/agent")
    team,agent=address.split("/",1)
    if not team or not agent or "/" in agent: raise ValueError("address must contain one team and agent")
    if realm in ("mac","win","mini","dell","windows"): realm=DEVICES[realm]
    elif realm not in ("local","personal","team"): raise ValueError("unknown realm: "+realm)
    return {"realm":realm,"team":TEAMS.get(team,team),"agent":agent}

def packets():
    return list(sorted((ROOT/"inbox/mac").glob("*.json")))+list(sorted((ROOT/"inbox/mac/triage").glob("*.json")))+list(sorted((ROOT/"pending/windows_to_mac").glob("*.json")))

def load(path):
    try:
        obj=json.loads(path.read_text()); return obj if isinstance(obj,dict) else None
    except Exception: return None

def classify(p):
    pres=load(ROOT/"presence/mac.json") or {}
    agents=os.environ.get("AGMSG_LOCAL_AGENTS",",".join(pres.get("agents",["secretary"]))).split(",")
    teams=os.environ.get("AGMSG_LOCAL_TEAMS",",".join(pres.get("teams",["a-sys","m3e","research","family","engineering","business"]))).split(",")
    to=p.get("to","")
    return to if to in agents else (p.get("team") if p.get("team") in teams else "triage")

def cmd_receive(args):
    action=args[0] if args else "list"
    seen=json.loads((STATE/"delivered.json").read_text()) if (STATE/"delivered.json").exists() else {}
    if action=="list":
        for f in packets():
            p=load(f)
            if p: print("\t".join([str(p.get("id","")),classify(p),str(p.get("from","")),str(p.get("team","")),f"delivered={bool(seen.get(str(p.get('id'))))}",str(p.get("title",p.get("id",""))).replace("\t"," "),str(f)]))
        return
    if len(args)<2: raise ValueError("receive open|verify|mark <id>")
    act,ident=args[0],args[1]
    if not re.fullmatch(r"[A-Za-z0-9._-]+",ident): raise ValueError("invalid message id")
    found=[(f,load(f)) for f in packets()]; found=[x for x in found if x[1] and x[1].get("id")==ident]
    if not found: raise ValueError("message not found: "+ident)
    f,p=found[0]
    if act=="open": print(json.dumps({"id":ident,"from":p.get("from"),"team":p.get("team"),"to_resolved":classify(p),"body":p.get("body",""),"packet":str(f)},ensure_ascii=False,indent=2))
    elif act=="verify":
        out=STATE/"received"/ident; out.mkdir(parents=True,exist_ok=True)
        for a in p.get("attachments",[]):
            src=pathlib.Path(a.get("path","")); src=src if src.is_absolute() else ROOT/src
            if not src.resolve().is_relative_to(ROOT.resolve()): raise ValueError("attachment path escapes Bridge root")
            if not src.is_file(): raise ValueError("attachment missing: "+str(src))
            digest=hashlib.sha256(src.read_bytes()).hexdigest()
            if digest.lower()!=str(a.get("sha256","")).lower(): raise ValueError("sha256 mismatch: "+str(src))
            dest=out/src.name
            if src.resolve()!=dest.resolve(): shutil.copy2(src,dest)
        print("verified extracted="+str(out))
    elif act=="mark":
        STATE.mkdir(parents=True,exist_ok=True); seen[ident]={"status":"delivered","at":dt.datetime.now(dt.timezone.utc).isoformat()}; (STATE/"delivered.json").write_text(json.dumps(seen,indent=2)+"\n"); print("marked delivered "+ident)
    else: raise ValueError("unknown receive action")

def cmd_watcher(seed=False):
    state=STATE/"watcher-seen.json"; STATE.mkdir(parents=True,exist_ok=True)
    seen=set(json.loads(state.read_text())) if state.exists() else set(); created=0
    current=[]
    for f in packets():
        p=load(f)
        if p and p.get("id"): current.append(p["id"])
    if seed:
        before=len(seen); seen.update(current)
        state.write_text(json.dumps(sorted(seen),indent=2)+"\n")
        print(f"seeded={len(seen)-before} seen={len(seen)}")
        return
    for f in packets():
        p=load(f)
        if not p or not p.get("id") or p["id"] in seen: continue
        team=p.get("team","triage"); to=classify(p); body="Bridge message: "+str(p.get("body", ""))[:350]
        send=pathlib.Path.home()/".agents/skills/agmsg/scripts/send.sh"
        if not send.is_file(): raise ValueError("agmsg send.sh missing")
        subprocess.run(["bash",str(send),team,"bridge",to,body,"--force"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        seen.add(p["id"]); created+=1
    state.write_text(json.dumps(sorted(seen),indent=2)+"\n"); print(f"created={created} seen={len(seen)}")

def presence(agents,teams,runtime):
    d=ROOT/"presence"; d.mkdir(parents=True,exist_ok=True)
    data={"device":"mac","agents":[x for x in agents.split(",") if x],"runtime":runtime,"teams":[TEAMS.get(x,x) for x in teams.split(",") if x],"heartbeat_utc":dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")}
    (d/"mac.json").write_text(json.dumps(data,indent=2)+"\n")

def directory():
    now=dt.datetime.now(dt.timezone.utc)
    for f in sorted((ROOT/"presence").glob("*.json")):
        try:
            p=json.loads(f.read_text()); stamp=dt.datetime.fromisoformat(p["heartbeat_utc"].replace("Z","+00:00")); status="present" if (now-stamp).total_seconds()<=900 else "absent"
            print(f"{p.get('device',f.stem)}\t{status}\tagents={','.join(p.get('agents',[]))}\tteams={','.join(p.get('teams',[]))}")
        except Exception: continue

def main():
    a=sys.argv[1:]
    if not a: raise ValueError("command required")
    op=a.pop(0)
    if op=="parse": print(json.dumps(parse(a[0]),indent=2)); return
    if op=="validate-kind":
        realm,kind=a[0],a[1]
        if kind.startswith("request.") and realm not in ("mac","win","mini"): raise ValueError("request.* requires one physical device realm")
        if realm in ("personal","team") and not (kind=="notice" or kind.startswith("notice.")): raise ValueError("group realms allow notices only")
        return
    if op=="receive": cmd_receive(a); return
    if op=="watcher": cmd_watcher("--seed" in a); return
    if op=="presence":
        if a[0]=="write": presence(a[1],a[2],a[3] if len(a)>3 else "unknown"); return
    if op=="directory": directory(); return
    raise ValueError("unsupported command: "+op)

if __name__=="__main__":
    try: main()
    except Exception as e: print("agmsg-routing: "+str(e),file=sys.stderr); sys.exit(2)
