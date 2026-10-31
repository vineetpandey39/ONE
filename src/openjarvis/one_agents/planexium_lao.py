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
    # Package/process identity is stable. A changed workflow is a new version
    # of the same dependency, not a brand-new dependency in LAO's catalog.
    package_name = name
    version = hashlib.sha256(workflow.encode("utf-8")).hexdigest()[:12]
    manifest = {"name": package_name, "version": version, "entrypoint": "workflow.yaml",
                "runtime_type": "browser", "input_schema": {"type": "object", "properties": {}},
                "output_schema": {"type": "object", "properties": outputs}}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package.json", json.dumps(manifest))
        archive.writestr("workflow.yaml", workflow)
    return package_name, version, stream.getvalue()


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
    # Reuse LAO's existing package/version/process/job APIs.
    if not payload.get("folder_id"):
        raise ValueError("PLANEXIUM package requires its explicit scoped folder")
    name, version_name, archive = workflow_zip(payload["name"], payload["steps"])
    folder_id = str(payload["folder_id"])
    package = _find_in_scopes(
        client, "/packages",
        lambda row: row.get("name") == name and str(row.get("folder_id")) == folder_id,
    )
    if package is None:
        package = client.post("/packages", {"name": name, "folder_id": folder_id,
                                           "description": "PLANEXIUM isolated production workflow"})

    versions = client.get(f"/packages/{package['id']}/versions") or []
    version = next((row for row in versions if row.get("version") == version_name), None)
    if version is None:
        response = httpx.post(client.base_url + "/packages/" + package["id"] + "/versions",
            headers=client._headers(), data={"version": version_name},
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
        process_payload = {
            "name": process_name,
            "folder_id": folder_id,
            "package_version_id": version["id"],
            "input_defaults": process.get("input_defaults") or {},
            "required_assets": process.get("required_assets") or [],
            "priority": process.get("priority", 100),
            "retry_policy": process.get("retry_policy") or {"max_attempts": 1, "backoff_seconds": 0},
            "timeout_seconds": process.get("timeout_seconds", 10800),
        }
        if hasattr(client, "put"):
            process = client.put(f"/processes/{process['id']}", process_payload)
        else:
            response = httpx.put(
                client.base_url + f"/processes/{process['id']}",
                headers=client._headers(), json=process_payload, timeout=client.timeout,
            )
            response.raise_for_status()
            process = response.json()
    job = client.post("/jobs", {"process_id": process["id"], "input_args": payload["input_args"]})
    return {"job": job, "process_id": process["id"], "package_id": package["id"],
            "package_version_id": version["id"]}
