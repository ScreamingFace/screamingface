# Changelog

## [0.2.0](https://github.com/ScreamingFace/screamingface/compare/scoreboard-v0.1.1...scoreboard-v0.2.0) (2026-10-09)


### Features

* **scoreboard:** accept and store what a run's cache hits would have cost ([#1055](https://github.com/ScreamingFace/screamingface/issues/1055)) ([494a5fa](https://github.com/ScreamingFace/screamingface/commit/494a5fa3508470e06cf6da05d2218d642cdd72de))
* **scoreboard:** add an operator command that deletes named scores ([#1079](https://github.com/ScreamingFace/screamingface/issues/1079)) ([f1402b0](https://github.com/ScreamingFace/screamingface/commit/f1402b04c0c0542b6679fd9d9d2b80f072e2a273))
* **scoreboard:** compute the open share over the cost/score Pareto frontier ([#1080](https://github.com/ScreamingFace/screamingface/issues/1080)) ([5fd16fb](https://github.com/ScreamingFace/screamingface/commit/5fd16fb482aca484375352394946cf4319d8c52d))
* **scoreboard:** mark each leaderboard entry as open or closed weights ([#1081](https://github.com/ScreamingFace/screamingface/issues/1081)) ([5596ca9](https://github.com/ScreamingFace/screamingface/commit/5596ca93a4aab8a07c4c00fda919e8fd8f8c8e13))
* **scoreboard:** portal logo links home, one consistent breadcrumb ([#1308](https://github.com/ScreamingFace/screamingface/issues/1308)) ([fc8cb9c](https://github.com/ScreamingFace/screamingface/commit/fc8cb9ca30d066289469627a4cd3a2d2a2c678c7))
* **scoreboard:** rank and show the reproduction cost, spend plus both cache savings ([#1227](https://github.com/ScreamingFace/screamingface/issues/1227)) ([8c4db51](https://github.com/ScreamingFace/screamingface/commit/8c4db51e31ab23a64fcc617e9a59d6a26a699f38))
* **scoreboard:** split readiness from liveness with a DB-aware /readyz ([49959fa](https://github.com/ScreamingFace/screamingface/commit/49959faff3b9c82685e8073459a0328962b760c6))
* **scoreboard:** split readiness from liveness with a DB-aware /readyz (OME-944) ([ba1545d](https://github.com/ScreamingFace/screamingface/commit/ba1545d8180fc97ae05061ccff2ff9410dc8dd43))
* **screamingface-engine:** declare Benchmark provenance and serve a saturation verdict ([7d1efb4](https://github.com/ScreamingFace/screamingface/commit/7d1efb4b61d1c06ea0acb014b44ad966a3947a25))
* **screamingface-engine:** declare Benchmark provenance and serve a saturation verdict (OME-1455, PR 2 of 4) ([8561d57](https://github.com/ScreamingFace/screamingface/commit/8561d57af23c348ad4ae2885b04853d6e28fb54c))
* **screamingface-engine:** source the provenance of every registered Benchmark and empty the allowlist ([37fef37](https://github.com/ScreamingFace/screamingface/commit/37fef37d8786b051ff440854b0dcc93f77e3415f))
* **screamingface-engine:** source the provenance of every registered Benchmark and empty the allowlist (OME-1455, PR 3 of 4) ([ec767b1](https://github.com/ScreamingFace/screamingface/commit/ec767b168f98bf7760591d30dbbbe325a69a6a42))


### Bug Fixes

* **scoreboard:** configure app logging and honor SCOREBOARD_LOG_LEVEL ([93acb12](https://github.com/ScreamingFace/screamingface/commit/93acb121a1e5468964291674700a8c6a8afa1da9))
* **scoreboard:** configure app logging and honor SCOREBOARD_LOG_LEVEL (OME-937) ([0b7e3d8](https://github.com/ScreamingFace/screamingface/commit/0b7e3d82d5c1c0b3ef8d27297dc6ed773b27dd07))
* **scoreboard:** drop the self-reported-costs disclaimer on the Pareto chart ([#1123](https://github.com/ScreamingFace/screamingface/issues/1123)) ([ea9f8d7](https://github.com/ScreamingFace/screamingface/commit/ea9f8d7c88f367330d7209c8b2268488056fd988))
* **scoreboard:** keep the reproduction cost unknown when a saving cannot be read ([#1259](https://github.com/ScreamingFace/screamingface/issues/1259)) ([b885aa2](https://github.com/ScreamingFace/screamingface/commit/b885aa224013b9a10ed9bf0617f9f126e2f14539))
* **scoreboard:** name the request connection in every transaction ([#1244](https://github.com/ScreamingFace/screamingface/issues/1244)) ([c08ce63](https://github.com/ScreamingFace/screamingface/commit/c08ce63eba91f53e020ac682b535acf066db0915))
* **scoreboard:** reserve a readiness DB connection and size the pool explicitly ([#1213](https://github.com/ScreamingFace/screamingface/issues/1213)) ([aa582c1](https://github.com/ScreamingFace/screamingface/commit/aa582c12e30e17f527528d8bf649df1e696a2b51))
