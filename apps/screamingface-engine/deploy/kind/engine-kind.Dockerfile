# syntax=docker/dockerfile:1.7
# Kind-only overlay (uniform executor test-plan §5): layers the kind environment's declared
# world (a `/corpus/papers` data route added to the shipped defaults, see url4-kind.toml) onto
# the already-built engine image. Never used outside deploy/kind — the shared
# apps/screamingface-engine/url4.toml stays untouched, and `Dockerfile.benchmark` builds FROM
# this image unchanged, so the benchmark image carries the same world.
#
# INVARIANT: build context is the REPO ROOT, exactly like the base Dockerfile — this only adds
# one COPY layer on top of it.
#
#   docker build -f apps/screamingface-engine/Dockerfile -t screamingface-engine:kind-base .
#   docker build -f apps/screamingface-engine/deploy/kind/engine-kind.Dockerfile \
#       --build-arg BASE=screamingface-engine:kind-base -t screamingface-engine:kind .
ARG BASE=screamingface-engine:kind-base
FROM ${BASE}
USER 0
COPY apps/screamingface-engine/deploy/kind/url4-kind.toml /etc/url4/url4.toml
USER 1000
