from pathlib import Path
base=Path('C:/Users/pc/AppData/Local/Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude/local-agent-mode-sessions/cb3dc5b9-a76c-45ff-bbcf-b330fe30c84a/21738b93-8e02-4c20-a83c-0abb35d85c72/local_374e1c90-a56c-4744-840b-8f0118a3547a/outputs/lao-platform/robot-worker')
p=base/'activities/browser_activities.py';s=p.read_text();s=s.replace('assistant_baseline: int | None = None,\n    ) -> str:', 'assistant_baseline: int | None = None,\n        strict_fresh_turn: bool = False,\n    ) -> str:')
s=s.replace('''                        const baselineAssistantCount = (baselineArg && baselineArg.assistantCount) || 0;''','''                        const baselineAssistantCount = (baselineArg && baselineArg.assistantCount) || 0;
                        const strictFresh = !!(baselineArg && baselineArg.strictFresh);
                        const freshTurns = Array.from(document.querySelectorAll("[data-message-author-role='assistant']"));
                        const freshScope = freshTurns[freshTurns.length - 1];
                        if (strictFresh && freshTurns.length <= baselineAssistantCount) {
                            return {src: "", count: 0, diag: [{reason: "awaiting_new_assistant_turn"}]};
                        }''')
s=s.replace('''                        let visible = Array.from(nodes).filter((el) => {
                            const rect''','''                        let visible = Array.from(nodes).filter((el) => {
                            if (strictFresh && (!freshScope || !freshScope.contains(el))) return false;
                            const rect''')
s=s.replace('"assistantCount": baseline_assistant_count', '"assistantCount": baseline_assistant_count, "strictFresh": strict_fresh_turn')
p.write_text(s)
p=base/'workflow_engine.py';s=p.read_text();s=s.replace('selector, dest, stall_timeout_ms, poll_ms, preferred_choice, assistant_baseline\n','selector, dest, stall_timeout_ms, poll_ms, preferred_choice, assistant_baseline,\n                    strict_fresh_turn=bool(args.get("strict_fresh_turn", False))\n');p.write_text(s)
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/origin_to_ovation.py');s=p.read_text();s=s.replace('"allow_fresh_chat_recovery": False,','"allow_fresh_chat_recovery": False, "strict_fresh_turn": True,');p.write_text(s)
import py_compile
for p in [base/'activities/browser_activities.py',base/'workflow_engine.py']:py_compile.compile(str(p),doraise=True)
