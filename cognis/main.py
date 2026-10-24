"""Typer entrypoint for Cognis."""

from __future__ import annotations

# Must run before litellm/tiktoken/huggingface_hub are imported anywhere.
from cognis.offline_runtime import configure_offline_runtime

configure_offline_runtime()

import httpx  # noqa: E402
import typer  # noqa: E402

from cognis.cli.admin import admin_app, print_env_template  # noqa: E402
from cognis.cli.database import database_app  # noqa: E402
from cognis.cli.executor import executor_app  # noqa: E402
from cognis.cli.serve import serve  # noqa: E402
from cognis.config import load_config  # noqa: E402

app = typer.Typer(invoke_without_command=True, help="Cognis controller")
config_app = typer.Typer(help="Configuration helpers")
app.add_typer(admin_app, name="admin")
app.add_typer(config_app, name="config")
app.add_typer(database_app, name="db")
app.add_typer(executor_app, name="executor")


@app.callback()
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        serve()


@app.command("serve")
def serve_command() -> None:
    serve()


@config_app.command("init")
def config_init() -> None:
    print_env_template()


@app.command()
def status() -> None:
    config = load_config()
    host = "127.0.0.1" if config.host == "0.0.0.0" else config.host
    response = httpx.get(f"http://{host}:{config.port}/api/health", timeout=5)
    typer.echo(response.text)
