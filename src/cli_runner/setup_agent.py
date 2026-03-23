from __future__ import annotations

import sys
from cli_runner.adapters import REGISTRY, get_adapter

def run_status() -> int:
    """Print the installation status of all agents."""
    print(f"{'Agent':<10} {'Status':<10} {'Path'}")
    print("-" * 40)
    for name in REGISTRY:
        adapter = get_adapter(name)
        installed = adapter.is_installed()
        status = "[FOUND]" if installed else "[MISSING]"
        path = ""
        if installed:
            resolved = adapter.resolve_cmd()
            if resolved:
                path = resolved[0]
        print(f"{name:<10} {status:<10} {path}")
    return 0

def run_setup(agent_name: str | None = None, yes: bool = False, dry_run: bool = False) -> int:
    """Detect and install missing agents."""
    agents_to_setup = [agent_name] if agent_name and agent_name != "all" else list(REGISTRY.keys())
    
    for name in agents_to_setup:
        adapter = get_adapter(name)
        if adapter.is_installed():
            print(f"Agent '{name}' is already installed.")
            continue
        
        if not yes and not dry_run:
            confirm = input(f"Agent '{name}' is missing. Install it? [y/N]: ").strip().lower()
            if confirm != "y":
                print(f"Skipping '{name}'.")
                continue
        
        success = adapter.install(dry_run=dry_run)
        if success and not dry_run:
            if adapter.post_install_verify():
                print(f"Successfully installed and verified '{name}'.")
            else:
                print(f"Install reported success for '{name}' but binary not found on PATH. You may need to restart your terminal.")
        elif not success:
            print(f"Failed to install '{name}'.")
            
    return 0
