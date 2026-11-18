# How to explain and extend this project

## Follow one request

1. `static/index.html` sends two files and typed options with `FormData`.
2. `BodyLimit` counts the received bytes before multipart parsing. It does not trust `Content-Length`.
3. The route checks file size, reads dimensions, rejects unsupported raster formats and normalizes EXIF orientation/transparency.
4. `artifact_id` hashes decoded pixel arrays and normalized options. Re-encoding an identical RGB image with different JPEG/PNG metadata does not itself change the key; a lossy re-encoding can change pixels and therefore the key.
5. A cached bundle bypasses processing. Otherwise `engine.transfer` transforms source pixels using reference statistics.
6. The source-shaped output becomes a PNG. Metadata and PNG are published together, avoiding a split state where metadata references a missing image.
7. The UI retrieves the image with the same access key and presents a download link.

## Numerical ideas to understand

- RGB channel matching is `(x - mean(x)) * std(y)/std(x) + mean(y)`. What happens when `std(x)=0`? Why can clipping prevent exact statistical matching?
- Covariance matching uses `Cy^(1/2) Cx^(-1/2)` on centered column vectors. Why are three independent channel scalings insufficient for correlated colors? Why regularize small eigenvalues?
- lαβ converts RGB to LMS, takes logarithms and rotates into a decorrelated space. Explain why this differs from CIE Lab and why log(0) requires a floor.
- Sliced transfer projects into random orthogonal coordinates, matches sorted one-dimensional distributions, rotates back and takes a partial step. Quantile interpolation handles unequal pixel counts. Its main cost is repeated sorting, roughly `O(iterations × (Ns log Ns + Nr log Nr))`.
- Strength blending happens after the transformed RGB is clipped. Explain this choice and alternatives.

## Systems questions to practice

- **Why synchronous HTTP?** Small bounded images and a simpler observable first version. CPU execution uses a worker thread. Larger jobs require a queue/process workers; making CPU code `async def` would not make it parallel.
- **Why no database?** Results are immutable artifacts accessed by ID, without list/search/user ownership requirements. S3 already provides object storage. Adding SQL now would create unnecessary cross-storage consistency work.
- **What if two requests share the same key?** They may both compute. Local atomic publication keeps a complete first bundle. S3 writes complete objects; concurrent writes may replace observational metadata, but the same versioned inputs/options describe the same output. There is no exactly-once guarantee.
- **What if the process dies?** Before commit, readers see no final artifact. A temporary local file may remain. After commit, readers see a complete bundle. File fsync and atomic publication do not establish arbitrary hardware power-loss guarantees.
- **Why one bundle?** Two independent files would introduce a commit ordering problem. A single object keeps metadata and image together, at the cost of reading the bundle to retrieve either part.
- **What does the API key protect?** A single-owner demo. It does not provide separate user identities, per-user quotas or tenant isolation.
- **What would you measure?** Processing vs request latency, warm vs cold starts, image size, iteration count, cache-hit ratio, memory use and output clipping. A palette mean error alone does not measure perceptual quality.

## Concrete next contributions

1. Add a new test image pair and explain a failure case where global palette matching produces unnatural colors.
2. Add clipping-rate and covariance-distance metrics to result metadata, with numerical tests.
3. Profile sliced transfer across pixel counts and iteration counts; publish reproducible measurements.
4. Add a cancelable asynchronous job API only after measuring a need for longer processing.
5. Deploy the existing template in your account, verify access controls and binary responses, then document actual AWS results.

