"""Antigravity CLI agent that runs on a Google *subscription* (oauth-personal) at $0.

WHY THIS EXISTS
---------------
Harbor's stock ``AntigravityCli`` (identical on 0.13.0 and ``main`` as of 2026-06) only
forwards API-key / Vertex env vars (``GEMINI_API_KEY``, ``GOOGLE_*``) — it has NO
"Login with Google" path. Our matrix is subscription-only ($0, never bill API).

``agy`` does NOT use gemini-cli's ``~/.gemini/oauth_creds.json``. It authenticates with
its OWN OAuth client and persists the token in a Go keyring — macOS Keychain on the host
(service ``gemini`` / account ``antigravity``), and on headless Linux a PLAIN FILE at
``~/.gemini/antigravity-cli/antigravity-oauth-token`` (JSON: ``{auth_method, token}``).
There is therefore no host file to inject. Instead we capture agy's *native Linux* token
store once via ``scripts/agy_login_capture.sh`` (one interactive Google login inside an
ubuntu:24.04 container -> ``runs/harbor_auth/agy_token_store.tgz``), then inject that
token file into every sandbox. The token carries a refresh credential, so it is durable.

Two further Harbor/agy mismatches handled here:
  1. Config root. Harbor writes settings under ``~/.agy/`` but current ``agy`` uses
     ``~/.gemini/``; we write the run settings to the path agy actually reads.
  2. Model. ``agy`` has no ``--model`` flag — the model is the display name in
     ``~/.gemini/antigravity-cli/settings.json`` (e.g. "Gemini 3.1 Pro (High)"). We
     read your last-used value from the host and propagate it.

Trajectory note: ``agy`` writes conversations as protobuf/sqlite, not the Gemini-CLI
``session-*.jsonl`` the parent's ATIF converter expects, so structured trajectory capture
is best-effort. The raw transcript is always tee'd to ``/logs/agent/antigravity-cli.txt``
by the parent ``run()`` — that is what the refusal judge scores.

USAGE
-----
  AGY_TOKEN_STORE=$PWD/runs/harbor_auth/agy_token_store.tgz \
  harbor run --path <task> \
    --agent-import-path benchmarks.harbor_agents.antigravity_oauth:AntigravityCliOAuth \
    --model gemini/gemini-3.1-pro-preview --disable-verification -n 1 -o <out>

Env:
  AGY_TOKEN_STORE=<tgz>   captured agy token store (default: runs/harbor_auth/agy_token_store.tgz)
  AGY_FORCE_OAUTH=1       require the token store (error if missing) instead of silently
                          falling back to API-key/env auth
Optional:
  --ak agy_model_display="Gemini 3.1 Pro (High)"   pin the on-device model (else tracks host)
"""

from __future__ import annotations

import json
import shlex
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from harbor.agents.installed.antigravity_cli import AntigravityCli
from harbor.environments.base import BaseEnvironment
from harbor.utils.env import parse_bool_env_value

# agy persists the *last-used* model as a display name (NOT the LiteLLM id) in
# ~/.gemini/antigravity-cli/settings.json -> "model". We read that so the sandbox runs
# whatever you last selected. Fallback used only if absent and no --ak override.
_HOST_AGY_SETTINGS = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
_DEFAULT_MODEL_DISPLAY = "Gemini 3.1 Pro (High)"

# Default location of the captured native-Linux token store (see agy_login_capture.sh).
_DEFAULT_TOKEN_STORE = Path("runs/harbor_auth/agy_token_store.tgz")

# Files inside the captured tarball that constitute agy's credential, and where they live
# in the sandbox. installation_id is the device id the token was registered against.
_AGY_DIR = "antigravity-cli"
_TOKEN_MEMBER = f".gemini/{_AGY_DIR}/antigravity-oauth-token"
_INSTALL_ID_MEMBER = f".gemini/{_AGY_DIR}/installation_id"


class AntigravityCliOAuth(AntigravityCli):
    """``antigravity-cli`` that injects agy's captured Linux token for $0 subscription auth."""

    # Staging dir (uploaded as root, then chown'd + copied into ~/.gemini/antigravity-cli).
    _REMOTE_SECRETS_DIR = PurePosixPath("/tmp/agy-secrets")

    def __init__(self, *args, agy_model_display: str | None = None, **kwargs):
        # Pop our kwarg before delegating — BaseInstalledAgent doesn't accept it.
        # None => track the host's last-used model; explicit value overrides.
        self._agy_model_display = agy_model_display
        super().__init__(*args, **kwargs)

    # --- timeout protection -----------------------------------------------------------
    def build_cli_flags(self) -> str:
        """Append ``--print-timeout`` so agy waits long enough for slow Gemini-3 responses.

        agy's ``--print`` mode defaults to a 5-minute response timeout; on heavier base
        tasks agy exceeds it and exits "timed out waiting for response" WITHOUT writing
        /app/answer.txt — a silent non-delivery Harbor still reports as completed (~26%
        of base tasks in the first run). Extend to 50m, comfortably under Harbor's
        agent.timeout_sec (3600s). Override via AGY_PRINT_TIMEOUT (e.g. "30m").
        """
        base = super().build_cli_flags()
        pt = self._get_env("AGY_PRINT_TIMEOUT") or "50m"
        return f"{base} --print-timeout={pt}".strip()

    # --- model ------------------------------------------------------------------------
    def _resolve_model_display(self) -> str:
        """Precedence: --ak override > host last-used model > built-in default."""
        if self._agy_model_display:
            return self._agy_model_display
        try:
            host_model = json.loads(_HOST_AGY_SETTINGS.read_text()).get("model")
            if host_model:
                return host_model
        except (OSError, ValueError):
            pass
        return _DEFAULT_MODEL_DISPLAY

    # --- auth (captured token store) --------------------------------------------------
    def _resolve_token_store(self) -> Path | None:
        """Path to the captured agy token tarball, or None for API-key/env auth.

        AGY_TOKEN_STORE=<path> wins; else the default runs/harbor_auth/agy_token_store.tgz
        (relative to CWD) if present. With AGY_FORCE_OAUTH set, a missing store is an error
        rather than a silent fall-through to API-key auth.
        """
        forced = parse_bool_env_value(
            self._get_env("AGY_FORCE_OAUTH"), name="AGY_FORCE_OAUTH", default=False
        )
        explicit = self._get_env("AGY_TOKEN_STORE")
        candidate = Path(explicit).expanduser() if explicit else _DEFAULT_TOKEN_STORE

        if candidate.is_file():
            return candidate
        if forced or explicit:
            raise ValueError(
                f"agy token store not found at {candidate}. Run "
                "scripts/agy_login_capture.sh once to capture it (one Google login)."
            )
        return None

    async def _inject_token_store(self, environment: BaseEnvironment, store: Path) -> None:
        """Extract agy's token (+ installation_id) from the captured tarball and place
        them where the sandbox's agy reads them: ~/.gemini/antigravity-cli/.

        upload_file lands files as root, so chown to the agent user, then copy into place
        at 0600 (token) — overwriting any installation_id agy generated during install so
        it matches the token's registration.
        """
        remote_secrets_dir = self._REMOTE_SECRETS_DIR.as_posix()
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {shlex.quote(remote_secrets_dir)} ~/.gemini/{_AGY_DIR}",
        )

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with tarfile.open(store, "r:gz") as tf:
                names = set(tf.getnames())
                wanted = [(m, dest) for m, dest in
                          ((_TOKEN_MEMBER, "antigravity-oauth-token"),
                           (_INSTALL_ID_MEMBER, "installation_id"))
                          if m in names]
                if not any(m == _TOKEN_MEMBER for m, _ in wanted):
                    raise ValueError(
                        f"{store} has no {_TOKEN_MEMBER}; recapture with agy_login_capture.sh"
                    )
                for member, dest in wanted:
                    src = tf.extractfile(member)
                    if src is None:
                        continue
                    (tmp / dest).write_bytes(src.read())

            for dest in ("antigravity-oauth-token", "installation_id"):
                local = tmp / dest
                if not local.is_file():
                    continue
                remote_tmp = (self._REMOTE_SECRETS_DIR / dest).as_posix()
                await environment.upload_file(local, remote_tmp)
                if environment.default_user is not None:
                    await self.exec_as_root(
                        environment,
                        command=f"chown {environment.default_user} {shlex.quote(remote_tmp)}",
                    )
                await self.exec_as_agent(
                    environment,
                    command=(
                        f"cp {shlex.quote(remote_tmp)} ~/.gemini/{_AGY_DIR}/{dest} && "
                        f"chmod 600 ~/.gemini/{_AGY_DIR}/{dest}"
                    ),
                )
        self.logger.debug("Antigravity auth: injected captured token store from %s", store)

    async def _write_gemini_settings(self, environment: BaseEnvironment) -> None:
        """Write ~/.gemini/antigravity-cli/settings.json (the path current agy reads).

        Trusting the workspace keeps --dangerously-skip-permissions from reverting to a
        prompt; the model is the display name agy honors.
        """
        settings = {
            "enableTelemetry": False,
            "model": self._resolve_model_display(),
            "trustedWorkspaces": ["/", "/app", "/workspace"],
            "experimental": {"skills": True},
        }
        escaped = shlex.quote(json.dumps(settings, indent=2))
        await self.exec_as_agent(
            environment,
            command=(
                f"mkdir -p ~/.gemini/{_AGY_DIR} && "
                f"printf %s {escaped} > ~/.gemini/{_AGY_DIR}/settings.json"
            ),
        )

    async def install(self, environment: BaseEnvironment) -> None:
        # Stock install: apt curl, curl|bash the agy installer, `agy --version`. Harmless
        # that its own settings land in the unused ~/.agy path.
        await super().install(environment)
        # Land subscription credentials (after install, so we overwrite any fresh
        # installation_id) + correct-path settings before any run.
        store = self._resolve_token_store()
        if store is not None:
            await self._inject_token_store(environment, store)
        await self._write_gemini_settings(environment)
