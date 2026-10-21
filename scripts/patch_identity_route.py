from pathlib import Path
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/origin_to_ovation.py');s=p.read_text();needle='''        if manifest.get("production_phase") == "reference_first":
            from openjarvis.one_agents.chandan_reference''';s=s.replace(needle,'''        if payload.get("checkpoint") == "identity_repair_v3":
            from openjarvis.one_agents.chandan_identity_repair import run
            return run(path, job)
        if manifest.get("production_phase") == "reference_first":
            from openjarvis.one_agents.chandan_reference''');p.write_text(s)
