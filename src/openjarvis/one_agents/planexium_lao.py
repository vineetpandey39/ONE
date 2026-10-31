"""Opt-in PLANEXIUM transport preserving conditional shared workflow semantics."""
import io
import hashlib
import json
import zipfile
import httpx
import yaml


def workflow_zip(name, steps):
    if not name.startswith("planexium-"):
        raise ValueError("Preserved package transport is restricted to PLANEXIUM")
    outputs = {
        alias: {}
        for step in steps
        if isinstance(step, dict)
        for alias in [step.get("args", {}).get("as")]
        if isinstance(alias, str) and alias
    }
    workflow = yaml.safe_dump({"name": name, "step_pacing_ms": 2500,
                               "steps": steps}, sort_keys=False)
    # The old UUID suffix created a permanent LAO package and process for every
    # retry. A content fingerprint preserves isolation when the workflow really
    # changes while allowing identical runs to reuse one dependency pair.
    package_name = f"{name}-{hashlib.sha256(workflow.encode('utf-8')).hexdigest()[:12]}"
    manifest = {"name": package_name, "version": "1.0.0", "entrypoint": "workflow.yaml",
                "runtime_type": "browser", "input_schema": {"type": "object", "properties": {}},
                "output_schema": {"type": "object", "properties": outputs}}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package.json", json.dumps(manifest))
        archive.writestr("workflow.yaml", workflow)
    return package_name, stream.getvalue()


def _find_in_scopes(client, resource, predicate):
    for scope in ("production", "non-production", "non_production", "nonproduction", "all"):
        try:
            rows = client.get(resource, scope=scope) or []
        except httpx.HTTPStatusError:
            continue
        match = next((row for row in rows if predicate(row)), None)
        if match:
            return match
    return None


def run_preserved_workflow(client, payload):
    # Reuse LAO's existing package/version/process/job APIs. No backend patch,
    # service restart, new dependency or edit to an existing process is needed.
    if not payload.get("folder_id"):
        raise ValueError("PLANEXIUM package requires its explicit scoped folder")
    name, archive = workflow_zip(payload["name"], payload["steps"])
    folder_id = str(payload["folder_id"])
    package = _find_in_scopes(
        client, "/packages",
        lambda row: row.get("name") == name and str(row.get("folder_id")) == folder_id,
    )
    if package is None:
        package = client.post("/packages", {"name": name, "folder_id": folder_id,
                                           "description": "PLANEXIUM isolated production workflow"})

    versions = client.get(f"/packages/{package['id']}/versions") or []
    version = next((row for row in versions if row.get("version") == "1.0.0"), None)
    if version is None:
        response = httpx.post(client.base_url + "/packages/" + package["id"] + "/versions",
            headers=client._headers(), data={"version": "1.0.0"},
            files={"file": ("package.zip", archive, "application/zip")}, timeout=client.timeout)
        response.raise_for_status()
        version = response.json()

    process_name = "Studio draft run - " + name
    process = _find_in_scopes(
        client, "/processes",
        lambda row: row.get("name") == process_name and str(row.get("folder_id")) == folder_id,
    )
    if process is None:
        process = client.post("/processes", {"name": process_name,
            "folder_id": folder_id, "package_version_id": version["id"],
            "input_defaults": {}, "required_assets": [], "priority": 100,
            "retry_policy": {"max_attempts": 1, "backoff_seconds": 0}, "timeout_seconds": 10800})
    elif str(process.get("package_version_id")) != str(version["id"]):
        raise RuntimeError(f"LAO process '{process_name}' points at an unexpected package version")
    job = client.post("/jobs", {"process_id": process["id"], "input_args": payload["input_args"]})
    return {"job": job, "process_id": process["id"], "package_id": package["id"],
            "package_version_id": version["id"]}
