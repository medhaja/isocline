# CLI

Installed with the SDK: `isocline`. Configure once (`~/.isocline/config.json`, mode 0600) or use `ISOCLINE_URL` /
`ISOCLINE_TOKEN`. `--json` gives machine-readable output.

```bash
isocline login --url http://localhost:8000 --token isc_pat_...
isocline projects list
isocline workflows list [--project <id>]
isocline validate workflow.json [--project <id>]          # exit 1 if invalid or preflight BLOCKED
isocline run <workflow-id-or-name> [--project <id>] --input '{"company": "Acme"}' [--stream] [--version N]
                                                            # exit 0 completed, 1 failed, 2 waiting
isocline runs get <run-id> [--nodes]
isocline artifacts get <artifact-id> [-o file]
isocline evaluate <workflow> --project <id> --dataset <id> [--min-pass-rate 0.9]
```
