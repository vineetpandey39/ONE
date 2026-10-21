from pathlib import Path
base=Path('C:/Users/pc/AppData/Local/Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude/local-agent-mode-sessions/cb3dc5b9-a76c-45ff-bbcf-b330fe30c84a/21738b93-8e02-4c20-a83c-0abb35d85c72/local_374e1c90-a56c-4744-840b-8f0118a3547a/outputs/lao-platform/robot-worker')
p=base/'activities/browser_activities.py';s=p.read_text(encoding='utf-8');s=s.replace('strict_fresh_turn: bool = False,\n','strict_fresh_turn: bool = False,\n        request_marker: str = "",\n')
a='''                        const freshScope = freshTurns[freshTurns.length - 1];
                        if (strictFresh && freshTurns.length <= baselineAssistantCount) {
                            return {src: "", count: 0, diag: [{reason: "awaiting_new_assistant_turn"}]};
                        }'''
b='''                        const marker = (baselineArg && baselineArg.requestMarker) || "";
                        const userTurns = Array.from(document.querySelectorAll("[data-message-author-role='user']"));
                        const requestTurn = marker ? userTurns.filter(el => (el.innerText || "").includes(marker)).pop() : null;
                        const candidatesAfterRequest = requestTurn ? freshTurns.filter(el => !!(requestTurn.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) : [];
                        const freshScope = marker ? candidatesAfterRequest[candidatesAfterRequest.length - 1] : freshTurns[freshTurns.length - 1];
                        if (strictFresh && (marker ? !freshScope : freshTurns.length <= baselineAssistantCount)) {
                            return {src: "", count: 0, diag: [{reason: "awaiting_assistant_after_exact_request"}]};
                        }'''
assert a in s;s=s.replace(a,b);s=s.replace('const scope = turns.length ? turns[turns.length - 1] : document;','const scope = strictFresh ? freshScope : (turns.length ? turns[turns.length - 1] : document);')
s=s.replace('"strictFresh": strict_fresh_turn}', '"strictFresh": strict_fresh_turn, "requestMarker": request_marker}')
p.write_text(s,encoding='utf-8')
p=base/'workflow_engine.py';s=p.read_text(encoding='utf-8');s=s.replace('preferred_choice, assistant_baseline, strict_fresh_turn=True)','preferred_choice, assistant_baseline, strict_fresh_turn=True,\n                        request_marker=str(args.get("request_marker") or ""))');p.write_text(s,encoding='utf-8')
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/origin_to_ovation.py');s=p.read_text();s=s.replace('"prompt": shot["prompt"],\n            "reference_image_path"','"prompt": shot["prompt"] + "\\nRequest marker: OTO-" + path.name + "-" + shot["shot_id"],\n            "request_marker": "OTO-" + path.name + "-" + shot["shot_id"],\n            "reference_image_path"');p.write_text(s)
import py_compile
for p in [base/'activities/browser_activities.py',base/'workflow_engine.py']:py_compile.compile(str(p),doraise=True)
