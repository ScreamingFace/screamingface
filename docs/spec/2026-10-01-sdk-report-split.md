# SDK report recovery and pagination split contract

The runtime PR owns persistent local Engine artifact configuration, 0700 default-directory permissions, writer/reader path parity, override handling, and status showing the absolute serving path and size. It changes no Engine wire contract, remote storage, artifact TTL or SDK Report API. It incorporates implemented runtime work from #1211 at 12b8a390 and the relative-path correction from #1156.

The SDK PR owns durable completion records, verified downloads, disk-backed cases, recovery/partial failures, streamed atomic Report export and bounded notebook rendering/navigation. It works with the existing main Engine storage and retention policy, without the runtime PR.

Both PRs target main. Either may merge first; neither is stacked. Tests are relocated rather than weakened or removed from the combined implementation.
