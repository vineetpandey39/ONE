from pathlib import Path
p=Path('C:/Users/pc/AppData/Local/Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude/local-agent-mode-sessions/cb3dc5b9-a76c-45ff-bbcf-b330fe30c84a/21738b93-8e02-4c20-a83c-0abb35d85c72/local_374e1c90-a56c-4744-840b-8f0118a3547a/outputs/lao-platform/robot-worker/workflow_engine.py');s=p.read_text(encoding='utf-8');s=s.replace('''                downloaded_path = self.session.download_image_src(
                    selector, dest, stall_timeout_ms, poll_ms, preferred_choice, assistant_baseline,
                    strict_fresh_turn=bool(args.get("strict_fresh_turn", False))
                )''','''                if args.get("strict_fresh_turn"):
                    # Opt-in hot path refreshes the method without restarting the
                    # shared worker or replacing the owned browser session.
                    import importlib
                    import activities.browser_activities as browser_impl
                    browser_impl = importlib.reload(browser_impl)
                    downloaded_path = browser_impl.BrowserSession.download_image_src(
                        self.session, selector, dest, stall_timeout_ms, poll_ms,
                        preferred_choice, assistant_baseline, strict_fresh_turn=True)
                else:
                    downloaded_path = self.session.download_image_src(
                        selector, dest, stall_timeout_ms, poll_ms, preferred_choice, assistant_baseline)
''');p.write_text(s,encoding='utf-8')
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/chandan_identity_repair.py');s=p.read_text().replace('corrections-v4','corrections-v5').replace('age19-v4','age19-v5').replace('identity-v4','identity-v5');p.write_text(s)
p=Path('E:/ONE-SUITE/src/scripts/run_virat_floor_repair_v4.py');s=p.read_text().replace(':identity-repair-v4',':identity-repair-v5');Path('E:/ONE-SUITE/src/scripts/run_virat_floor_repair_v5.py').write_text(s)
