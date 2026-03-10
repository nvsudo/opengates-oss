from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import uvicorn

from .gates import GateLoader
from .settings import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opengates")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the local intake app.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    subparsers.add_parser("list-gates", help="List available gates.")

    init_gate = subparsers.add_parser("init-gate", help="Copy a starter gate.")
    init_gate.add_argument("--from", dest="source_gate", default="demo-investor")
    init_gate.add_argument("--to", dest="target_gate", required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()

    if args.command == "serve":
        uvicorn.run("opengates.app:app", host=args.host, port=args.port, reload=False)
        return

    if args.command == "list-gates":
        gate_loader = GateLoader(settings.gates_dir)
        for gate_id in gate_loader.list_gates():
            print(gate_id)
        return

    if args.command == "init-gate":
        source_path = settings.gates_dir / args.source_gate
        target_path = settings.gates_dir / args.target_gate
        if not source_path.exists():
            raise SystemExit(f"source gate not found: {source_path}")
        if target_path.exists():
            raise SystemExit(f"target gate already exists: {target_path}")
        shutil.copytree(source_path, target_path)
        rename_gate_yaml(target_path, args.target_gate)
        print(f"created {target_path}")
        return

    raise SystemExit("unknown command")


def rename_gate_yaml(target_path: Path, gate_id: str) -> None:
    gate_yaml = target_path / "gate.yaml"
    if not gate_yaml.exists():
        return
    lines = gate_yaml.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    for line in lines:
        if line.startswith("gate_id:"):
            updated.append(f"gate_id: {gate_id}")
        elif line.startswith("title:"):
            updated.append(f"title: {gate_id.replace('-', ' ').title()}")
        elif line.startswith("assistant_name:"):
            updated.append(f"assistant_name: {gate_id.replace('-', ' ').title()}")
        else:
            updated.append(line)
    gate_yaml.write_text("\n".join(updated) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
