"""Channel-scoped production services using the existing tools, without runtime wiring.

Adapters receive explicit brand/root arguments; callers must not wrap a legacy
Sonia-only adapter and label it channel-aware. No adapter is invoked on import.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

from openjarvis.one_agents.youtube_channels import ProductionContext

Adapter = Callable[..., dict[str, Any]]


class ExistingPrivateUploader:
    """Reuse the installed uploader in a private module instance per channel.

    No copying its implementation, changing environment variables or mutating
    the module used by Sonia. Credential values are resolved only by the
    installed broker when an authorized upload is explicitly invoked.
    """

    def __init__(self, script: Path, *, credential_asset: str, channel_id: str, synthetic: str):
        import re

        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", credential_asset):
            raise ValueError("An explicit credential asset name is required")
        if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
            raise ValueError("A verified channel ID is required")
        if synthetic not in ("yes", "no"):
            raise ValueError("Synthetic-media disclosure requires an explicit yes/no decision")
        self.script = script
        self.credential_asset = credential_asset
        self.channel_id = channel_id
        self.synthetic = synthetic

    def __call__(self, *, package: dict, expected_channel_id: str, privacy: str, ledger: Path) -> dict:
        import hashlib
        import importlib.util
        from openjarvis.one_agents.planexium_seo import require_seo
        require_seo(package)

        if expected_channel_id != self.channel_id or package.get("channel_id") != self.channel_id:
            raise ValueError("Uploader binding and package identity disagree")
        if (privacy != "private" or package.get("upload", {}).get("privacyStatus") != "private"
                or package.get("upload", {}).get("publishAt") or package.get("public_publish_authorized")):
            raise PermissionError("Existing uploader adapter accepts private drafts only")
        ledger.parent.mkdir(parents=True, exist_ok=True)
        master = Path(package["master"])
        # A process can die after YouTube accepts the private draft but before
        # PLANEXIUM updates its health file.  Reconcile from the uploader's
        # durable master-hash ledger instead of calling YouTube again and
        # surfacing its duplicate refusal as a new production failure.
        master_sha256 = hashlib.sha256(master.read_bytes()).hexdigest()
        try:
            prior = json.loads(ledger.read_text(encoding="utf-8")).get(master_sha256) or {}
        except (OSError, ValueError):
            prior = {}
        if prior.get("video_id") and prior.get("privacy") == "private":
            return {"executed": False, "already_uploaded_as": prior["video_id"],
                    "video_id": prior["video_id"], "title": prior.get("title"),
                    "privacy": "private", "thumbnail_set": prior.get("thumbnail_set", False),
                    "studio_url": f"https://studio.youtube.com/video/{prior['video_id']}/edit",
                    "published": False, "reconciled_from_ledger": True}
        spec = importlib.util.spec_from_file_location(f"channel_uploader_{uuid.uuid4().hex}", self.script)
        if spec is None or spec.loader is None:
            raise RuntimeError("Installed YouTube uploader is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # These bindings belong solely to this newly loaded module instance.
        module.ASSET = self.credential_asset
        module.EXPECTED_CHANNEL_ID = self.channel_id
        module.LEDGER = ledger
        package_path = master.parent / "channel-upload-package.json"
        package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return module.run(
            package_path, video=master,
            thumbnail=Path(package["thumbnail_path"]) if package.get("thumbnail_path") else None,
            caption=Path(package["caption"]) if package.get("caption") else None,
            caption_language=package.get("upload", {}).get("defaultAudioLanguage", "en"),
            synthetic=self.synthetic, execute=True, post_comment=False,
        )


@contextmanager
def resource_lease(directory: Path, resource: str) -> Iterator[None]:
    """A non-waiting lease shared by *resource*, never by output channel.

    All consumers must adopt the same directory/key before unattended use.
    This does not replace the legacy acquisition lock or delete stale locks.
    """
    import re

    if not re.fullmatch(r"[a-z][a-z0-9_-]*", resource):
        raise ValueError("Invalid resource name")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{resource}.lock"
    owner = f"{os.getpid()}:{uuid.uuid4().hex}"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(owner)
    except FileExistsError as exc:
        raise RuntimeError(f"Shared production resource busy: {resource}") from exc
    try:
        yield
    finally:
        # Never remove a lease replaced by another owner.
        if path.is_file() and path.read_text(encoding="utf-8") == owner:
            path.unlink()


class ProductionServices:
    def __init__(self, context: ProductionContext):
        self.context = context

    def metadata(self, record: dict, *, llm=None, portrait_library: Path | None = None) -> dict:
        from openjarvis.one_agents.youtube_seo import build_package

        return build_package(
            record, master=self.context.artifact("edit/master.mp4"),
            plan_path=self.context.artifact("production-plan.json"), llm=llm,
            channel=self.context.channel, portrait_library=portrait_library,
        )

    def narration(self, texts: list[str], *, rate: int = -1, cloud_adapter: Adapter | None = None) -> dict:
        """Explicit voice policy; an original channel cannot inherit the host clone."""
        if self.context.channel.narration_backend.startswith("windows_"):
            if cloud_adapter is not None:
                raise ValueError("Local voice profiles cannot use a cloud narration adapter")
            from openjarvis.one_agents.windows_narration import synthesize

            return synthesize(self.context, texts, rate=rate)
        if cloud_adapter is None:
            raise ValueError("Host voice requires its explicitly bound existing narration adapter")
        return cloud_adapter(brand=self.context.channel.brand, texts=texts,
                             output_root=self.context.artifact("narration"))

    def thumbnail(self, package: dict, *, generate: Adapter, variant: int = 0) -> dict:
        """Reuse ChatGPT image transport and exact-text compositor, without a host portrait.

        ``generate`` is the existing image action adapter bound by the caller;
        its contract accepts prompt/output and returns a downloaded local path.
        Failure remains failure: no Sonia portrait or local portrait fallback.
        """
        from openjarvis.one_agents.thumbnail_compose import compose

        channel = self.context.channel
        channel.validate_record(package)
        if package.get("brand") != channel.brand:
            raise ValueError("Thumbnail package requires explicit channel identity")
        if channel.thumbnail_mode != "original":
            raise ValueError("Portrait channels retain their existing approved portrait workflow")
        spec = package["thumbnail"]
        if spec.get("portrait_library") or "portrait" in str(spec.get("generation_mode", "")).lower().replace("no portrait reference", ""):
            raise ValueError("Original thumbnail cannot carry portrait inputs")
        chosen = spec["variants"][variant]
        from openjarvis.one_agents.youtube_seo import ORIGINAL_THUMBNAIL_PROMPT

        # Use the trusted original-image template, never a package-supplied host template.
        prompt = ORIGINAL_THUMBNAIL_PROMPT.format(
            video_title=package["recommended_title"], destination=package["destination"],
            left_usp=chosen["left_usp"], thumbnail_text=chosen["text"],
        )
        if chosen.get("visual_direction"):
            prompt += "\nCreative direction: " + chosen["visual_direction"]
        if chosen.get("composition"):
            prompt += "\nComposition: " + chosen["composition"]
        if channel.brand == "planexium":
            prompt += ("\nPLANEXIUM THUMBNAIL GATE: one unmistakable episode-specific hero subject must occupy "
                       "45-70% of the canvas. Keep the hook in one compact text lane. Do not leave any other "
                       "empty quadrant, do not use generic space wallpaper, and do not create a collage. The "
                       "image must communicate the episode promise at phone size without relying on the title.")
        folder = self.context.artifact(f"thumbnail/variant-{variant + 1}")
        folder.mkdir(parents=True, exist_ok=True)
        generated = generate(prompt=prompt, output=folder / "base.png", brand=channel.brand)
        if not generated.get("ok"):
            raise RuntimeError("Original thumbnail generation failed; no portrait fallback")
        base = Path(generated["path"]).resolve()
        if not base.is_relative_to(folder.resolve()) or not base.is_file():
            raise ValueError("Image adapter must return the requested channel-local artifact")
        receipt = compose(base, chosen["text"], folder / "final.png",
                          primary=tuple(chosen.get("primary_colour", [255, 255, 255])),
                          accent=tuple(chosen.get("accent_colour", [255, 214, 0])))
        if not receipt.get("qc", {}).get("ok"):
            raise RuntimeError("Original thumbnail failed composition QC")
        receipt.update(brand=channel.brand, mission_id=self.context.mission_id,
                       generator="chatgpt_image_generation", portrait_used=False)
        (folder / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        return receipt

    def thumbnail_experiment(self, package: dict, *, generate: Adapter) -> dict:
        """Three original candidates; reuse ARES's measured pre-upload scoring."""
        import hashlib
        import shutil
        from openjarvis.one_agents.ares_thumbnail import score_thumbnail

        self.context.channel.validate_record(package)
        supplied = package["thumbnail"].get("variants") or []
        if not supplied:
            raise ValueError("Thumbnail experiment requires an authored hook")
        authored = (package.get('brand') == 'planexium' and
                    package.get('thumbnail_strategy', {}).get('mode') == 'episode_specific_concepts')
        if authored:
            if len(supplied) != 3:
                raise ValueError('Episode-specific thumbnail experiment requires three authored concepts')
            variants = [dict(v) for v in supplied]
            if len({v.get('composition', '').casefold().strip() for v in variants}) != 3:
                raise ValueError('Thumbnail compositions must differ')
        else:
            directions = [
                ("cinematic", "Wide cinematic planetary establishing composition; clean warm rim lighting", [255, 214, 0]),
                ("comparison", "Dramatic close-up subject comparison; contrasting scale and distance; clearly illustrative, not a scale diagram", [80, 220, 255]),
                ("minimalist", "Minimalist cosmic intrigue; strong silhouette, restrained detail, orange and cyan contrast", [255, 150, 70]),
            ]
            variants = []
            for i, (name, direction, accent) in enumerate(directions):
                source = supplied[i] if i < len(supplied) else supplied[0]
                variants.append({**source, "name": name, "visual_direction": direction, "accent_colour": accent})
        package["thumbnail"]["variants"] = variants
        results = []
        for index, variant in enumerate(variants):
            folder = self.context.artifact(f"thumbnail/variant-{index + 1}")
            checkpoint = folder / "experiment-checkpoint.json"
            request = hashlib.sha256(json.dumps({"brand": package["brand"], "title": package["recommended_title"],
                "subject": package["destination"], "variant": variant, "version": 1}, sort_keys=True).encode()).hexdigest()
            prior = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else None
            if prior:
                receipt = prior["result"]
                path = Path(receipt["path"])
                if (prior["request_hash"] != request or not path.resolve().is_relative_to(folder.resolve())
                        or not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != prior["sha256"]):
                    raise ValueError("Thumbnail variant changed; targeted repair required")
            else:
                receipt = self.thumbnail(package, generate=generate, variant=index)
                receipt.update(variant=variant["name"], text=variant["text"], creative=variant,
                    preupload_score=score_thumbnail(Path(receipt["path"]), receipt["qc"], variant, portrait=False))
                if authored:
                    receipt['preupload_score'].update(scale='internal_design_readiness_0_100',score_purpose='design_readiness_only',not_actual_ctr=True)
                checkpoint.write_text(json.dumps({"request_hash": request, "result": receipt,
                    "sha256": hashlib.sha256(Path(receipt["path"]).read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
            results.append(receipt)
        if len(results) != 3 or not all(r["qc"]["ok"] for r in results):
            raise RuntimeError("All three original thumbnail variants must pass QC before selection")
        diversity=None
        if authored:
            from openjarvis.one_agents.planexium_packaging import check_thumbnail_diversity
            diversity=check_thumbnail_diversity([row['path'] for row in results])
            for row in results:
                row['preupload_score'].update(scale='internal_design_readiness_0_100',score_purpose='design_readiness_only',not_actual_ctr=True)
        winner = max(results, key=lambda row: row["preupload_score"]["score"])
        final = self.context.artifact("thumbnail/final" + Path(winner["path"]).suffix)
        shutil.copy2(winner["path"], final)
        result = {"ok": True, "path": str(final), "brand": self.context.channel.brand,
                  "winner": winner["variant"], "winner_score": winner["preupload_score"], "variants": results,
                  "portrait_used": False, "generator": "chatgpt_image_generation",
                  "selection": "highest QC-passed transparent pre-upload score; stable variant-order tie-break; not actual CTR"}
        if authored:
            result.update(selection='highest design-readiness score among QC-passed distinct concepts; provisional, not an audience winner',
                          winner_status='provisional_editorial_default', audience_winner=None,
                          internal_score_role='design_readiness_only', image_diversity=diversity,
                          measurement_plan=package['thumbnail_strategy']['measurement_plan'])
        self.context.artifact("thumbnail/thumbnail-experiment.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    def acquire(self, requests: list[dict], *, adapter: Adapter) -> dict:
        """Provider logic stays in the existing adapter, output identity stays explicit.

        The adapter must honor the existing shared provider/browser coordination.
        A separate media root is NOT a separate browser ownership namespace.
        """
        return adapter(brand=self.context.channel.brand, mission_id=self.context.mission_id,
                       output_root=self.context.root, requests=requests)

    def capture(self, scenes: list[dict], *, allowed_hosts: tuple[str, ...], adapter: Adapter) -> dict:
        """OBS is optional; exact allowlisted public hosts only, no travel recipe mutation."""
        if not scenes:
            return {"ok": True, "skipped": True, "reason": "No explanatory capture requested"}
        for scene in scenes:
            parsed = urlsplit(scene["url"])
            if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts
                    or parsed.username or parsed.password or parsed.port not in (None, 443)):
                raise ValueError("Capture source is outside the channel allowlist")
        return adapter(brand=self.context.channel.brand, mission_id=self.context.mission_id,
                       output_root=self.context.artifact("captures"), scenes=scenes)

    def motion(self, stage: str, *, tools: Path, python: Path) -> subprocess.CompletedProcess:
        """Call the installed root-argument tools; never change process-wide env/globals.

        Travel-specific assembly/acquisition/QC scripts are intentionally not
        smuggled into this interface: their adapters require explicit contracts.
        """
        scripts = {
            "kinetic": "render_kinetic.py", "director_manifest": "compile_director.py",
            "motion_v3": "motion_v3/render_director_v3.py",
            "motion_v2": "motion_v2/render_director_v2.py",
        }
        if stage not in scripts:
            raise ValueError("Unknown shared motion stage")
        script = tools / scripts[stage]
        if not script.is_file() or not python.is_file():
            raise FileNotFoundError("Installed motion tool or interpreter is unavailable")
        args = [str(python), str(script), str(self.context.root)]
        if stage == "motion_v3":
            args += ["--history", str(self.context.artifact("direction-history"))]
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=14400)

    def upload_private(self, package: dict, *, expected_channel_id: str, adapter: Adapter,
                       authorized: bool = False) -> dict:
        """Private upload boundary. Adapter verifies authenticated identity before sending.

        No standing Sonia authority is inherited. Public release is outside this
        service and remains an explicit human action, including after a retry.
        """
        import re

        self.context.channel.validate_record(package)
        if package.get("brand") != self.context.channel.brand:
            raise ValueError("Upload package requires explicit channel identity")
        if not authorized:
            raise PermissionError("Private upload requires channel-specific authorization")
        if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", expected_channel_id):
            raise ValueError("A verified immutable YouTube channel ID is required")
        if package.get("channel_id") != expected_channel_id:
            raise ValueError("Package and authorized channel identity disagree")
        upload = package.get("upload", {})
        if (upload.get("privacyStatus") != "private" or upload.get("publishAt")
                or package.get("public_publish_authorized")):
            raise PermissionError("Shared uploader only accepts private drafts")
        # Validate file ownership before calling an external writer.
        for key in ("master", "thumbnail_path", "caption"):
            if key in package:
                path = Path(package[key]).resolve()
                if not path.is_relative_to(self.context.root.resolve()) or not path.is_file():
                    raise ValueError("Upload artifacts must exist inside the channel mission")
        if not package.get("master"):
            raise ValueError("A channel-local master is required")
        from openjarvis.one_agents.planexium_seo import require_seo
        require_seo(package)
        return adapter(package=package, expected_channel_id=expected_channel_id, privacy="private",
                       ledger=self.context.artifact("upload-ledger.json"))
