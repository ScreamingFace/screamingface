# Persistent local Engine artifacts split contract

The runtime PR owns persistent local Engine artifact configuration, 0700 default-directory permissions, writer/reader path parity, override handling, and status showing the absolute serving path and size. It changes no Engine wire contract, remote storage, artifact TTL or SDK Report API. It incorporates implemented runtime work from #1211 at 12b8a390 and the relative-path correction from #1156.

The SDK PR owns durable completion records, verified downloads, disk-backed cases, recovery/partial failures, streamed atomic Report export and bounded notebook rendering/navigation. It works with the existing main Engine storage and retention policy, without the runtime PR.

Both PRs target main. Either may merge first; neither is stacked. Tests are relocated rather than weakened or removed from the combined implementation.


A state record without a valid absolute `artifacts_dir` does not establish where the
serving process stores results. Status returns `null` path and size plus restart
guidance, regardless of the inspecting shell's environment. Adopting an existing
legacy process through `up` does not reconstruct this information. With no recorded
runtime, status may show the configured default directory.

Size sampling reports `null` / size unknown for permission failures in any inspection
step (folder stat, listing or entry stat). A genuinely absent folder is zero, and
concurrent entry deletion is skipped. These diagnostics do not change running health,
retention or the SDK recovery contract.
