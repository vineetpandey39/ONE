from openjarvis.core.credentials import inject_credentials
from openjarvis.one_agents.runtime import run_worker
from openjarvis.one_agents.wake import start_wake_listener


if __name__ == "__main__":
    # The worker is a separate OS process from the API server and does not
    # inherit credentials.toml-derived env vars from it. Without this, the
    # worker only sees whatever happens to already be in the parent shell's
    # environment, which is why tool calls (image_generate, leonardo_video_
    # generate, etc.) would intermittently see stale/missing API keys even
    # right after saving a fresh one via the Credential Wallet UI.
    inject_credentials()
    start_wake_listener()
    run_worker()
