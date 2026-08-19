"""
CLI interface for CDISC Builder v2.
Supports serving the interactive Web UI, building SDTM datasets, parsing ODM XML,
and exporting built-in Yamaa schemas and templates.
"""

import argparse
import os
import shutil
import sys
import webbrowser
from pathlib import Path
import uvicorn
from .pipeline import SDTMPipeline
from .odm_parser import ODMParser

SCHEMAS_DIR = Path(__file__).parent / "schemas"


def main():
    parser = argparse.ArgumentParser(
        prog="cdiscbuilder",
        description="CDISC Builder v2: Next-generation SDTM creation engine with EDC ODM XML ingestion & AI Yamaa Schema Synthesizer"
    )
    parser.add_argument("--version", "-v", action="version", version="CDISC Builder v2.0 (Yamaa Schema Standard)")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: app / serve
    app_parser = subparsers.add_parser("app", aliases=["serve", "ui"], help="Launch the interactive Web UI")
    app_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    app_parser.add_argument("--port", "-p", type=int, default=8000, help="Port number (default: 8000)")
    app_parser.add_argument("--open-browser", "-b", action="store_true", default=True, help="Automatically open browser")
    app_parser.add_argument("--no-browser", action="store_false", dest="open_browser", help="Do not open browser automatically")

    # Command: build
    build_parser = subparsers.add_parser("build", help="Build SDTM datasets from ODM XML and YAML specs (Headless)")
    build_parser.add_argument("--xml", "-x", type=str, required=True, help="Path to EDC ODM XML file")
    build_parser.add_argument("--specs", "-s", type=str, required=True, help="Directory containing YAML domain specs")
    build_parser.add_argument("--output", "-o", type=str, default="./sdtm_output", help="Directory to save SDTM datasets")
    build_parser.add_argument("--formats", "-f", type=str, default="parquet,csv,xpt", help="Comma-separated export formats (parquet,csv,xpt)")

    # Command: parse-odm
    parse_parser = subparsers.add_parser("parse-odm", help="Parse ODM XML into long-format dataset")
    parse_parser.add_argument("--xml", "-x", type=str, required=True, help="Path to EDC ODM XML file")
    parse_parser.add_argument("--output", "-o", type=str, default="long_data.csv", help="Output file path (.csv or .parquet)")

    # Command: schemas
    schema_parser = subparsers.add_parser("schemas", help="List or export built-in Yamaa schema standards & templates")
    schema_parser.add_argument("--export-dir", "-e", type=str, help="Directory to export built-in schema templates to")
    schema_parser.add_argument("--template", "-t", type=str, help="Specific template domain to print (e.g. DM, VS, LB, AE)")

    args = parser.parse_args()

    if args.command in ("app", "serve", "ui"):
        url = f"http://{args.host}:{args.port}"
        print(f"\n========================================================")
        print(f"  CDISC Builder v2 Web UI")
        print(f"  Running at: {url}")
        print(f"  Yamaa Schema Standard · Polars Engine · AI Synthesizer")
        print(f"========================================================\n")
        
        if args.open_browser:
            import threading
            import time
            def _open():
                time.sleep(1.0)
                webbrowser.open(url)
            threading.Thread(target=_open, daemon=True).start()

        uvicorn.run("cdiscbuilderv2.app.main:app", host=args.host, port=args.port, reload=False)

    elif args.command == "build":
        formats = [f.strip() for f in args.formats.split(",")]
        pipeline = SDTMPipeline(
            xml_path=args.xml,
            specs_dir=args.specs,
            output_dir=args.output
        )
        print(f"Ingesting ODM XML: {args.xml}")
        pipeline.ingest_odm()
        print(f"Building SDTM datasets into {args.output}...")
        results = pipeline.run(export_formats=formats)
        print("\n--- SDTM Build Summary ---")
        for log in pipeline.execution_logs:
            print(f"Domain {log['domain']:<10} -> {log['status']} ({log.get('rows', 0)} rows, {log.get('cols', 0)} cols)")
        print(f"\nAll datasets generated in: {args.output}")

    elif args.command == "parse-odm":
        print(f"Parsing ODM XML: {args.xml}")
        parser_obj = ODMParser(args.xml)
        out_path = Path(args.output)
        if out_path.suffix == ".parquet":
            parser_obj.df_long.write_parquet(out_path)
        else:
            parser_obj.df_long.write_csv(out_path)
        print(f"Saved long data to: {out_path} ({parser_obj.df_long.height} rows)")

    elif args.command == "schemas":
        templates_dir = SCHEMAS_DIR / "templates"
        if args.template:
            t_file = templates_dir / f"{args.template.lower()}.yaml"
            if t_file.exists():
                print(t_file.read_text())
            else:
                print(f"Template '{args.template}' not found. Available: {[p.stem.upper() for p in templates_dir.glob('*.yaml')]}")
        elif args.export_dir:
            out_dir = Path(args.export_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            for f in templates_dir.glob("*.yaml"):
                shutil.copy(f, out_dir / f.name)
            print(f"Exported {len(list(templates_dir.glob('*.yaml')))} schema templates to: {out_dir}")
        else:
            print("Built-in Yamaa Domain Schema Templates:")
            for f in sorted(templates_dir.glob("*.yaml")):
                print(f"  - {f.stem.upper():<10} ({f.stat().st_size} bytes)")
            print("\nUse `cdiscbuilder schemas --export-dir <dir>` to export all templates.")

    else:
        # Default: launch app
        print("Launching CDISC Builder v2 Web UI (default)...")
        uvicorn.run("cdiscbuilderv2.app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
