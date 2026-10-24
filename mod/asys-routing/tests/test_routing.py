import hashlib, json, os, pathlib, subprocess, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "lib/routing.py"

def run(*args, ok=True):
    p = subprocess.run(["python3", str(CLI), *map(str,args)], text=True, capture_output=True)
    if ok and p.returncode: raise AssertionError(p.stderr)
    if not ok and p.returncode == 0: raise AssertionError("expected failure")
    return p

class Routing(unittest.TestCase):
    def test_addresses(self):
        self.assertIn('"realm": "local"', run("parse", "m3e/worker").stdout)
        self.assertIn('"realm": "win"', run("parse", "dell:system/director").stdout)
        self.assertIn('"team": "a-sys"', run("parse", "personal:akaghef-system/secretary").stdout)
        self.assertIn('"team": "a-sys"', run("parse", "local:system/worker").stdout)
        run("parse", "wat:team/agent", ok=False); run("parse", "bad", ok=False)
    def test_request_group_rejected(self):
        run("validate-kind", "personal", "request.work", ok=False)
        run("validate-kind", "team", "notice", ok=True)
    def test_win_send_uses_legacy_compatible_queue_and_v2_fields(self):
        p=subprocess.run(["bash",str(ROOT/"route.sh"),"send","win:m3e/unknown-agent","secretary","test title","request.work"],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        packets=(pathlib.Path(os.environ["AGMSG_BRIDGE_ROOT"])/"pending/mac_to_windows").glob("*.json")
        data=next(json.loads(packet.read_text()) for packet in packets if json.loads(packet.read_text()).get("to")=="unknown-agent")
        self.assertEqual(data["schema"],"agmsg.message.v2"); self.assertEqual(data["realm"],"win")
        self.assertEqual(data["team"],"m3e"); self.assertEqual(data["to"],"unknown-agent")
    def test_legacy_inbox_personal_mac_reads_old_pending_queue(self):
        bridge=pathlib.Path(os.environ["AGMSG_BRIDGE_ROOT"]); inbox=bridge/"pending/windows_to_mac"; inbox.mkdir(parents=True,exist_ok=True)
        packet={"schema":"agmsg.message.v2","id":"legacy-inbox-fixture","team":"a-sys","from":"windows/worker","to":"secretary","kind":"message","thread":"","body":"fixture"}
        (inbox/"legacy-inbox-fixture.json").write_text(json.dumps(packet))
        p=subprocess.run(["bash",str(ROOT/"route.sh"),"inbox","personal:akaghef-system/mac"],text=True,capture_output=True,env=os.environ.copy())
        self.assertEqual(p.returncode,0,p.stderr); self.assertIn("legacy-inbox-fixture",p.stdout)
        (bridge/"pending/mac_to_windows").mkdir(parents=True,exist_ok=True)
        (bridge/"pending/mac_to_windows/from-mac.json").write_text(json.dumps({**packet,"id":"legacy-windows-fixture"}))
        p=subprocess.run(["bash",str(ROOT/"route.sh"),"inbox","personal:akaghef-system/windows"],text=True,capture_output=True,env=os.environ.copy())
        self.assertEqual(p.returncode,0,p.stderr); self.assertIn("legacy-windows-fixture",p.stdout)
    def test_install_seeds_before_enable_and_registers_runtime_timeout(self):
        base=pathlib.Path(os.environ["AGMSG_BRIDGE_ROOT"]).parent/"install-test"; base.mkdir(); home=base/"home"; live=base/"live"
        (live/"scripts/adapters").mkdir(parents=True); (live/"scripts/route.sh").write_text("old route\n")
        bridge=pathlib.Path(os.environ["AGMSG_BRIDGE_ROOT"]); legacy_inbox=bridge/"pending/windows_to_mac"; legacy_inbox.mkdir(parents=True,exist_ok=True)
        seeded_packet={"schema":"agmsg.message.v2","id":"installed-layout-seed","team":"a-sys","from":"windows/worker","to":"secretary","kind":"message","thread":"","body":"installed fixture"}
        (legacy_inbox/"installed-layout-seed.json").write_text(json.dumps(seeded_packet))
        stale={"matcher":"","hooks":[{"type":"command","command":str(live/"scripts/agmsg-routing/hooks/session-start.sh")+" --runtime claude-code","timeout":5}]}
        other={"matcher":"","hooks":[{"type":"command","command":"other-hook"}]}
        claude=base/"claude/settings.json"; claude.parent.mkdir(); claude.write_text(json.dumps({"preserved":True,"hooks":{"SessionStart":[stale,other,stale]}}))
        codex=base/"codex/hooks.json"; codex.parent.mkdir(); codex.write_text(json.dumps({"preserved":True,"hooks":{"SessionStart":[]}}))
        env=os.environ.copy(); env.update({"HOME":str(home),"AGMSG_LIVE_ROOT":str(live),"CLAUDE_SETTINGS":str(claude),"CODEX_HOOKS":str(codex)})
        p=subprocess.run(["bash",str(ROOT/"install.sh")],text=True,capture_output=True,env=env)
        self.assertEqual(p.returncode,0,p.stderr); self.assertLess(p.stdout.index("seeded="),p.stdout.index("launchctl bootstrap"))
        installed_route=live/"scripts/route.sh"
        legacy=subprocess.run(["bash",str(installed_route),"inbox","personal:akaghef-system/mac"],text=True,capture_output=True,env=env)
        self.assertEqual(legacy.returncode,0,legacy.stderr); self.assertIn("installed-layout-seed",legacy.stdout)
        received=subprocess.run(["bash",str(installed_route),"receive","list"],text=True,capture_output=True,env=env)
        self.assertEqual(received.returncode,0,received.stderr); self.assertIn("installed-layout-seed",received.stdout)
        self.assertIn("seeded=0",subprocess.run(["bash",str(installed_route),"watcher","--seed"],text=True,capture_output=True,env=env,check=True).stdout)
        self.assertIn("created=0",subprocess.run(["bash",str(installed_route),"watcher"],text=True,capture_output=True,env=env,check=True).stdout)
        backups=list(live.glob(".akaghef-backup-*")); self.assertEqual(len(backups),1)
        for file, runtime in ((claude,"claude-code"),(codex,"codex")):
            data=json.loads(file.read_text()); self.assertTrue(data["preserved"])
            entries=data["hooks"]["SessionStart"]
            routing=[h for e in entries for h in e["hooks"] if "agmsg-routing/hooks/session-start.sh" in h["command"]]
            self.assertEqual(len(routing),1); self.assertIn(runtime,routing[0]["command"]); self.assertEqual(routing[0]["timeout"],10)
        self.assertIn("other-hook",claude.read_text())
        hook_script=live/"scripts/agmsg-routing/hooks/session-start.sh"; cwd=base/"unmapped"; cwd.mkdir()
        hook_env=env.copy(); hook_env.pop("AGMSG_AGENT_ID",None); hook_env["AGMSG_BRIDGE_ROOT"]=str(pathlib.Path(os.environ["AGMSG_BRIDGE_ROOT"])); hook_env["AGMSG_STATE_DIR"]=str(pathlib.Path(os.environ["AGMSG_STATE_DIR"]))
        presence_file=bridge/"presence/mac.json"
        before_presence=presence_file.read_bytes() if presence_file.exists() else None
        hook_result=subprocess.run(["bash",str(hook_script),"--runtime","codex"],cwd=cwd,env=hook_env,text=True,capture_output=True,check=True)
        self.assertEqual(hook_result.stdout, "")
        self.assertEqual(presence_file.read_bytes() if presence_file.exists() else None, before_presence)
        storage=live/"scripts/lib/storage.sh"; storage.parent.mkdir(parents=True,exist_ok=True)
        storage.write_text('agmsg_storage_load(){ :; }\nstorage_list_unread(){ printf "%s|%s" "$1" "$2" > "$AGMSG_TEST_STORAGE_CAPTURE"; }\n')
        capture=base/"storage-args.txt"; hook_env["AGMSG_TEST_STORAGE_CAPTURE"]=str(capture)
        summary=subprocess.run(["bash",str(live/"scripts/route.sh"),"unread-summary","triage",""] ,cwd=cwd,env=hook_env,text=True,capture_output=True)
        self.assertEqual(summary.returncode,0,summary.stderr); self.assertTrue(capture.exists(),summary.stderr)
        self.assertEqual(capture.read_text(),"triage|triage")
    def test_triage_receive_attachments_and_mark(self):
        bridge = pathlib.Path(os.environ["AGMSG_BRIDGE_ROOT"])
        (bridge/"inbox/mac").mkdir(parents=True); (bridge/"inbox/mac/triage").mkdir()
        msg="m1"; content=b"hello"; att=bridge/"inbox/mac/a.txt"; att.write_bytes(content)
        packet={"schema":"agmsg.message.v2","id":msg,"team":"unknown","to":"missing","from":"win/worker","kind":"message","body":"hi","attachments":[{"path":"inbox/mac/a.txt","sha256":hashlib.sha256(content).hexdigest()}]}
        f=bridge/"inbox/mac/m1.json"; f.write_text(json.dumps(packet))
        self.assertIn("triage", run("receive", "list").stdout)
        run("receive", "open", msg)
        self.assertIn("verified", run("receive", "verify", msg).stdout)
        run("receive", "mark", msg)
        packet["attachments"][0]["sha256"]="0"*64; f.write_text(json.dumps(packet))
        run("receive", "verify", msg, ok=False)
        self.assertTrue(f.exists())
    def test_watcher_idempotent_and_presence_stale(self):
        bridge=pathlib.Path(os.environ["AGMSG_BRIDGE_ROOT"]); legacy=bridge/"pending/windows_to_mac"; legacy.mkdir(parents=True,exist_ok=True)
        (legacy/"w.json").write_text(json.dumps({"schema":"agmsg.message.v2","id":"w","team":"a-sys","from":"win/worker","to":"secretary","kind":"message","body":"x"}))
        seeded=run("watcher","--seed").stdout
        self.assertRegex(seeded,r"seeded=[1-9]"); self.assertIn("created=0",run("watcher").stdout)
        (legacy/"new-after-seed.json").write_text(json.dumps({"schema":"agmsg.message.v2","id":"new-after-seed","team":"a-sys","from":"win/worker","to":"secretary","kind":"message","body":"x"}))
        self.assertIn("created=1",run("watcher").stdout); self.assertIn("created=0",run("watcher").stdout)
        run("presence", "write", "", "a-sys", "codex")
        data=json.loads((bridge/"presence/mac.json").read_text()); data["heartbeat_utc"]="2000-01-01T00:00:00Z"
        self.assertEqual(data["agents"],[]); self.assertEqual(data["runtime"],"codex")
        (bridge/"presence/mac.json").write_text(json.dumps(data))
        self.assertIn("absent",run("directory").stdout)
    def test_watcher_refreshes_presence_with_live_roles_only(self):
        bridge=pathlib.Path(os.environ["AGMSG_BRIDGE_ROOT"]); skill=bridge.parent/"skill"; rundir=skill/"run"; rundir.mkdir(parents=True)
        (skill/"scripts").mkdir(); (skill/"scripts/lib").symlink_to(ROOT.parents[1]/"scripts/lib")
        exited=subprocess.Popen(["true"]); exited.wait()
        roles={("a-sys","director","claude-code",f"live-sid.{os.getpid()}"),("a-sys","worker","claude-code",f"dead-sid.{exited.pid}"),("m3e","director","claude-code",f"live-sid.{os.getpid()}")}
        for team,agent,runtime,owner in roles:
            (rundir/f"actas.{team}__{agent}.session").write_text(owner+"\n")
            (rundir/f"role-active.{team}__{agent}").write_text(f"session=s\nowner={owner}\nproject=/p\ntype={runtime}\nteam={team}\nagent={agent}\n")
        env=os.environ.copy(); env["AGMSG_SKILL_DIR"]=str(skill)
        p=subprocess.run(["bash",str(ROOT/"watcher.sh")],text=True,capture_output=True,env=env)
        self.assertEqual(p.returncode,0,p.stderr); self.assertIn("created=",p.stdout)
        data=json.loads((bridge/"presence/mac.json").read_text())
        self.assertEqual(data["device"],"mac"); self.assertEqual(data["agents"],["director"])
        self.assertEqual(sorted(data["teams"]),["a-sys","m3e"]); self.assertEqual(data["runtime"],"claude-code")
        self.assertRegex(data["heartbeat_utc"],r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual([f.name for f in (bridge/"presence").iterdir()],["mac.json"])
        self.assertIn("present",run("directory").stdout)

if __name__ == "__main__": unittest.main(verbosity=2)
