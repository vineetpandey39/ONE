"""Opt-in PLANEXIUM transport preserving conditional shared workflow semantics."""
import io
import json
import uuid
import zipfile
import httpx
import yaml


def workflow_zip(name, steps):
    if not name.startswith("planexium-"):
        raise ValueError("Preserved package transport is restricted to PLANEXIUM")
    package_name = name + "-" + uuid.uuid4().hex[:12]
    outputs = {
        alias: {}
        for step in steps
        if isinstance(step, dict)
        for alias in [step.get("args", {}).get("as")]
        if isinstance(alias, str) and alias
    }
    manifest = {"name": package_name, "version": "1.0.0", "entrypoint": "workflow.yaml",
                "runtime_type": "browser", "input_schema": {"type": "object", "properties": {}},
                "output_schema": {"type": "object", "properties": outputs}}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package.json", json.dumps(manifest))
        archive.writestr("workflow.yaml", yaml.safe_dump({"name": name, "step_pacing_ms": 2500,
                                                          "steps": steps}, sort_keys=False))
    return package_name, stream.getvalue()


def run_preserved_workflow(client, payload):
    # Reuse LAO's existing package/version/process/job APIs. No backend patch,
    # service restart, new dependency or edit to an existing process is needed.
    if not payload.get("folder_id"):
        raise ValueError("PLANEXIUM package requires its explicit scoped folder")
    name, archive = workflow_zip(payload["name"], payload["steps"])
    package = client.post("/packages", {"name": name, "folder_id": payload["folder_id"],
                                      "description": "PLANEXIUM isolated production workflow"})
    response = httpx.post(client.base_url + "/packages/" + package["id"] + "/versions",
        headers=client._headers(), data={"version": "1.0.0"},
        files={"file": ("package.zip", archive, "application/zip")}, timeout=client.timeout)
    response.raise_for_status()
    version = response.json()
    process = client.post("/processes", {"name": "Studio draft run - " + name,
        "folder_id": payload["folder_id"], "package_version_id": version["id"],
        "input_defaults": {}, "required_assets": [], "priority": 100,
        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0}, "timeout_seconds": 10800})
    job = client.post("/jobs", {"process_id": process["id"], "input_args": payload["input_args"]})
    return {"job": job, "process_id": process["id"], "package_id": package["id"],
            "package_version_id": version["id"]}
