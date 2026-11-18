# AWS deployment

This is an optional deployment path. Nothing here has been deployed to an AWS account. Prerequisites: Docker, AWS CLI, AWS SAM CLI, and credentials for your own account. Use a dedicated sandbox account/profile where possible.

## Architecture

`HTTPS → API Gateway HTTP API → Lambda (FastAPI/Mangum) → private S3 result bundles`

The default UI and API share an origin, so CORS is not enabled. The shared API key is enforced by the application on transfer and artifact routes; it is not an API Gateway usage-plan key. Public UI/docs/health routes can still invoke Lambda. Throttling and reserved concurrency limit traffic, but do not guarantee a spending cap.

## Build and validate

```sh
python scripts/prepare_lambda.py
sam validate --lint --region eu-west-3
sam build --use-container
sam deploy --guided --region eu-west-3
```

The staging script copies only the application and dependency manifests into
`build/lambda/`. It excludes local environments, image results, tests and unrelated
workspace files from the deployment bundle.

Use `chromatic-demo` for the stack name. During guided deploy, enter a freshly generated access key of at least 32 characters for `ApiKey`; `NoEcho` masks the parameter in CloudFormation. Do not put it in Git, command history or a public screenshot. Do not save parameter overrides to `samconfig.toml`; it is ignored as an additional precaution. Lambda's environment contains this key and is visible to appropriately authorized account administrators. For a production service, use a managed identity/authentication design and secret rotation.

SAM can request permission to create the function's IAM role. Review the changeset: Lambda only needs `s3:GetObject` and `s3:PutObject` on this bucket's `results/*` prefix, plus its logging permissions. The bucket blocks all public access and uses SSE-S3 encryption. Original uploads are not stored in S3.

The function is x86_64/Python 3.13 with 1,024 MiB memory, 28-second timeout and reserved concurrency of two. API Gateway is throttled to two requests/second with burst four. Test a 512×512, 30-iteration request on the actual AWS hardware before increasing the supported workload. HTTP API integration timeouts and Lambda payload quotas apply; the application bounds the multipart body below the synchronous Lambda payload limit after base64 encoding. For larger images, the next design would use direct S3 uploads plus asynchronous queued processing.

## Verify the deployment

1. Open `StudioUrl` from the stack outputs; `/healthz` should return `status: ok`.
2. Use the browser-generated demo images. Expand **Cloud access key**, enter the key, and submit.
3. Confirm a PNG is returned; repeat and verify **Cached result**.
4. Submit without a key and confirm 401. Confirm the S3 bucket has no public policy.
5. Inspect CloudWatch logs for structured transfer events and errors. Never log the key.
6. Record AWS region, memory, cold/warm latency and measured cost separately from local benchmark results.

AWS charges can accrue for Lambda, API Gateway, S3, logs and SAM build/package artifacts. Set your own AWS Budget before deployment. No free-tier assumption is made.

## Retention and cleanup

Result objects expire after seven days through S3 lifecycle rules; deletion is not immediate. CloudWatch logs retain seven days. The S3 bucket is retained when the stack is deleted, preventing accidental loss. SAM's managed deployment-artifact bucket can also remain.

To retire your deployment, run `sam delete --stack-name chromatic-demo --region eu-west-3`, inspect retained resources in your account, and explicitly empty/delete the result bucket only when you intend to discard its images. Do not delete unrelated SAM resources used by other stacks.

