from pathlib import Path
p=Path('E:/ONE-SUITE/src/src/openjarvis/one_agents/origin_to_ovation.py');s=p.read_text();s=s.replace('''        plan = read(master_dir / "shot-plan.json")
        write(path / "runtime" / "active.json", {''','''        plan = read(master_dir / "shot-plan.json")
        if (path / "runtime" / "identity-quarantine.json").exists():
            release_path = path / "runtime" / "identity-release.json"
            if not release_path.is_file():
                return {"_blocked": True, "status": "identity_review_required",
                        "blocked_reason": "Quarantined frames require hash-bound visual identity, anatomy and period review"}
            release = read(release_path)
            for shot in plan:
                gate = release.get("shots", {}).get(shot["shot_id"], {})
                if (gate.get("image_sha256") != digest(Path(shot["image"]))
                        or gate.get("reference_sha256") != digest(Path(shot["reference"]))
                        or not all(gate.get(k) is True for k in ("identity", "anatomy", "historical_accuracy"))):
                    return {"_blocked": True, "status": "identity_review_required",
                            "blocked_reason": "Every quarantined scene needs a matching passed visual gate"}
        write(path / "runtime" / "active.json", {''');p.write_text(s)
