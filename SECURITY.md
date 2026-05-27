# Security

FocusParse is a research harness for controlled document-QA experiments. It is
not designed to run untrusted user questions, uploaded PDFs, or model-authored
code as a public service.

## Secrets

Do not commit provider keys, Modal tokens, Hugging Face tokens, source PDFs, or
derived private run artifacts. Use `.env` locally and keep generated artifacts
under ignored directories such as `results/` and `cache/`.

## Sandbox Boundary

`run_python` is a research-grade subprocess sandbox with import allowlists and
resource limits. Treat it as a convenience for benchmark experiments, not as a
production isolation boundary for hostile code.

## Reporting

If this repository is published under `run-llama`, report security issues
through the organization’s normal private disclosure channel. Avoid opening
public issues that include secrets, private documents, or exploit details.
