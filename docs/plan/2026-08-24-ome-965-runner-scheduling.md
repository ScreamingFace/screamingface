# OME-965 — Runner Job scheduling plan

## Implementation

1. Add failing adapter tests for configured and empty scheduling values.
2. Add failing factory tests for settings propagation.
3. Add failing chart contract tests for JSON scheduling settings.
4. Add typed Runner scheduling settings.
5. Pass the settings through the factory.
6. Copy the settings into each Runner Pod specification.
7. Render the existing Helm scheduling values into the Engine ConfigMap.
8. Update the Engine chart documentation.
9. Run the ScreamingFace Engine gate suite.

## Safety

The chart owns environment-specific values. The adapter only transports and
applies their Kubernetes-native structure. Empty defaults preserve existing
deployments.
