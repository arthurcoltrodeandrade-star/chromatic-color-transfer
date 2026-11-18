# Verification record

Checked 18 November 2026 on Windows, Python 3.13.7, using the isolated `.venv` in this project.

| Check | Result |
|---|---|
| pytest | 45 passed |
| Python line coverage | 97.51% (281 statements, 7 missed) |
| Ruff | All checks passed |
| pip dependency consistency | No broken requirements |
| AWS SAM/CloudFormation template | `cfn-lint template.yaml --region eu-west-3` passed |
| Browser workflow | Generated demo images → covariance and sliced transfers → cache hit → PNG preview and download link verified |
| S3 adapter | AWS SDK calls verified with botocore Stubber; no AWS connection |
| Lambda binary response | Mangum HTTP API events accepted base64 multipart uploads and returned base64 PNG |
| Docker image | Build and container health check passed in GitHub Actions on Ubuntu; Docker is absent locally |
| Actual AWS deployment | Not performed; SAM CLI/AWS CLI absent, no account/resources accessed |
| GitHub Actions | First Test and build run passed (49 seconds), including Python and AWS-template jobs |

The pytest run requires local socket creation on Windows (asyncio/TestClient). The restricted shell environment blocked that socket pair; tests passed when run with local networking allowed. Two upstream deprecation warnings remain: Starlette's httpx TestClient compatibility and Mangum's event-loop creation in the Lambda adapter test. They do not fail the suite.

## Algorithm benchmark

Command: `python scripts/benchmark.py --size 256 --repeats 5`.
Generated RGB images, seed 42, one warm-up per method; sliced transfer uses 12 iterations.

| Method | Median ms | Min–max ms | RGB palette mean error |
|---|---:|---:|---:|
| RGB | 8.76 | 8.68–9.10 | 0.018 |
| Logarithmic lαβ | 16.23 | 16.08–17.30 | 0.053 |
| Covariance | 7.81 | 7.46–8.31 | 0.003 |
| Sliced | 252.57 | 251.65–256.22 | 3.571 |

These are local, algorithm-only measurements on a generated pair. They exclude upload, decode, PNG encoding, storage, network and cloud cold starts. They are not throughput guarantees, AWS measurements or perceptual-quality rankings. RGB mean error is the Euclidean distance between reference and output channel means in 0–255 units.

## Tests worth discussing in an interview

- A covariance test checks off-diagonal channel statistics, rather than checking only output dimensions.
- Constant and one-pixel images exercise zero-variance/singular-matrix handling.
- Sliced transfer works with unequal image sizes and reduces palette mean error on a controlled input.
- Cache tests recreate the application before retrieving a result, proving persistence beyond process-local state.
- Concurrent readers/writers check that metadata and PNG cannot come from different incomplete writes.
- A chunked-body test verifies the upload guard without relying on Content-Length.
- Stubbed S3 tests distinguish missing objects from access-denied failures.

The concurrent-write test originally exposed Windows file replacement failing while another thread read the destination. Publication now uses a complete temporary file plus an atomic hard link, with first-writer-wins behavior locally.

GitHub CI verification: initial commit `733413d`, workflow run #1, completed successfully on 18 November 2026. AWS account deployment is still unperformed.
