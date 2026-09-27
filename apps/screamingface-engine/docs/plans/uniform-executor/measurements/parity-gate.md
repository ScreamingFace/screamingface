# Parity gate: node tier → direct runs (uniform executor PRD 05, DC-H1)

This record decides whether the node tier may be removed. `scripts/parity_gate_check.py` (DEC-1)
checks it. Each item is PASS only with its evidence named.

## 1. Every MNT test is green, including MNT-9 against the MNT-C2 status table

Evidence (2026-09-27, branch `exp/uniform-executor`): every MNT test is green.

| MNT | Test | Where |
|---|---|---|
| 1–4, 8 (url4) | test_dispatch_direct_refuses_eval_path, test_dispatch_direct_calls_one_endpoint_handler, test_dispatch_direct_serves_data_route_with_media_type, test_describe_routes_lists_endpoints_and_data_routes, test_an_observed_direct_call_reports_one_node_with_its_usage | packages/url4 tests/unit/test_direct_dispatch.py (26 passed with `-k "direct or http_status"`) |
| 5 | test_no_private_url4_dispatch_import.py | engine unit |
| 6–8 | test_direct_shape_runs_dispatch_direct_not_dag, test_tampered_eval_target_fails_direct_eval_refused, test_direct_run_yields_span_and_cost_for_the_model_call | test_direct_run_executor.py |
| 9, C2 | test_mount_status_mapping_matches_node_tier_table (the MNT-C2 status table) | test_mount_routes.py |
| 10–23 | test_mount_call_publishes_direct_run_and_returns_200 … test_admission_503_for_mount_calls | test_mount_routes.py |
| 24 | test_local_mount_direct_run.py | integration |
| 25 | K3 (mount calls + OpenAPI), K4 (1.5 MiB → 303 → artifact 200) | kind |
| 26 | test_mnt26_killing_the_runner_pod_mid_mount_call_redelivers_or_504 | kind |
| C1 | forwarder identity strip + 403 — passed before the removal; after it, test_missing_identity_403_nothing_queued and test_request_scope.py::test_forwarded_headers_keep_only_the_allowlist_and_the_verified_identity | unit |
| C3 | test_a_mount_shadowed_by_an_engine_route_fails_startup_naming_both | test_world_mount_guard.py |
| C4 | test_local_node_mount.py, test_one_accessor_lists_every_path_a_node_serves | unit |

Runs: engine unit suite 4311 passed (the 7 failures are `test_chart_render_node_tier.py`, which
this removal deletes); integration in the Linux container 70 passed, 0 skipped; the MNT subset
71 passed; the kind suite below.

Result: PASS

## 2. Every node-tier behavior is ported or recorded as not applicable

The 89 tests of the 7 node-tier test files. A row names the direct-path test that holds the same
behavior, or says why it does not apply once the tier is gone. Paths are under
`apps/screamingface-engine/tests/` (unit unless named `integration`), and `packages/url4/tests/unit/`
for `test_direct_dispatch.py`.

| file | test | behavior | direct-path test or N/A: reason |
|---|---|---|---|
| test_node_tier.py | test_the_ladder_numbers_live_in_settings_and_decrease_inward | timeout ladder decreases inward | N/A: the node's own timeout ladder; a direct run's deadline is sync_max_wait_s+5 — test_mount_routes.py::test_mount_call_publishes_direct_run_and_returns_200 (deadline_s == 10) |
| test_node_tier.py | test_the_tier_overrides_allow_outbound_and_the_aigateway_timeout | tier config overrides | N/A: a direct run builds the SAME world a run does (declared config); no tier overrides exist |
| test_node_tier.py | test_a_started_tier_keeps_url4s_default_eval_path | eval path stays /v1 | test_mount_routes.py::test_eval_path_is_404_in_production |
| test_node_tier.py | test_a_mount_call_returns_the_model_answer | mount returns model answer | test_mount_routes.py::test_mount_call_publishes_direct_run_and_returns_200; test_mount_direct_run_spine.py |
| test_node_tier.py | test_two_concurrent_sync_requests_keep_their_own_caller_state | concurrent callers isolated | test_mount_routes.py::test_two_concurrent_mount_calls_each_carry_their_own_identity |
| test_node_tier.py | test_a_request_without_a_verified_identity_is_still_scoped_not_anonymous | no unverified identity | test_mount_routes.py::test_missing_identity_403_nothing_queued |
| test_node_tier.py | test_a_slow_call_times_out_cleanly_and_cancels_the_gateway_call | slow call 504 + cancel | test_mount_routes.py::test_bound_elapsed_returns_504_and_stops_run; kind K5 |
| test_node_tier.py | test_a_known_mount_without_q_returns_400_naming_q | no q → 400 | test_mount_routes.py::test_endpoint_without_q_is_400_missing_intent |
| test_node_tier.py | test_an_unknown_path_still_404s_at_the_node | unknown path 404 | test_direct_dispatch.py::test_dispatch_direct_unknown_path_is_endpoint_not_found; test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[endpoint_not_found] |
| test_node_tier.py | test_a_colon_bearing_model_id_is_addressable_via_the_tilde_route | tilde route | test_mount_routes.py::test_a_tilde_encoded_model_mount_is_served_with_its_target_unchanged |
| test_node_tier.py | test_a_non_get_method_on_a_mount_returns_405 | non-GET 405 | test_mount_routes.py::test_a_wrong_method_on_a_mount_is_the_nodes_405_envelope |
| test_node_tier.py | test_the_in_flight_cap_sheds_with_503_and_retry_after | over capacity 503 | test_mount_routes.py::test_admission_503_for_mount_calls |
| test_node_tier.py | test_readiness_reports_503_until_the_world_is_ready | node readiness | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately; the App registers mounts in a startup hook and serves no request before it |
| test_node_tier.py | test_a_failed_collision_guard_marks_readiness_failed_and_refuses_to_start | collision fails startup | test_world_mount_guard.py::test_a_mount_shadowed_by_an_engine_route_fails_startup_naming_both |
| test_node_tier.py | test_a_started_tier_reports_ready | node /readyz | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier.py | test_the_world_builds_offline_and_calls_fail_502 | offline gateway 502 | test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[aigateway_transport_error] |
| test_node_tier.py | test_the_sync_surface_records_duration_and_inflight | node sync metrics | N/A: replaced by screamingface_engine_mount_calls_total — test_mount_routes.py::test_mount_calls_are_counted_by_path_and_status |
| test_node_tier.py | test_sync_request_logs_carry_origin_sync_and_the_trace_id | sync log origin | N/A: a mount call is a RUN now; run logs carry topic + trace id (test_run_scope / test_world_run_log_namespace.py) |
| test_node_tier.py | test_a_run_scope_line_carries_topic_and_trace_id_but_no_origin | run scope log | N/A: run-scope logging is unchanged and tested in the runner (test_world_run_log_namespace.py) |
| test_node_tier.py | test_node_mode_dispatches_to_the_node_entrypoint | CLI node mode | N/A: the `node` mode is removed — DEC-5 test_cli_rejects_node_mode |
| test_node_tier.py | test_node_resolves_the_real_node_entrypoint | node entrypoint import | N/A: the `node` mode is removed — DEC-5 |
| test_node_tier_review_round.py | test_a_spilling_request_still_holds_its_admission_slot | spill holds slot | N/A: the run holds its WORKER SLOT until the child exits (supervisor); test_mount_routes.py::test_result_over_1mib_returns_signed_303 |
| test_node_tier_review_round.py | test_a_shed_request_never_reaches_the_inner_app | shed never reaches handler | test_mount_routes.py::test_admission_503_for_mount_calls (nothing queued) |
| test_node_tier_review_round.py | test_a_non_overload_503_is_not_counted_as_shed | shed counter | N/A: the node's shed counter; queue admission has its own metrics (test_queue_metrics.py) |
| test_node_tier_review_round.py | test_a_retry_skipped_at_the_deadline_is_502_deadline_exceeded_and_counted | retry at deadline | test_mount_routes.py::test_bound_elapsed_returns_504_and_stops_run |
| test_node_tier_review_round.py | test_a_504_timeout_is_counted_as_budget_exhausted | 504 counted | test_mount_routes.py::test_bound_elapsed_returns_504_and_stops_run; mount_calls_total{status=504} |
| test_node_tier_review_round.py | test_a_plain_downstream_502_is_not_budget_exhausted | 502 not budget | N/A: the node's budget counter; the direct path counts by status — test_mount_routes.py::test_mount_calls_are_counted_by_path_and_status |
| test_node_tier_review_round.py | test_a_spill_timeout_records_one_sample_with_the_final_502 | spill timeout sample | N/A: the node's own spill; the child spills (test_artifact_spill_is_store_agnostic.py) and a spill failure is a terminal code — test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[artifact_spill_failed] |
| test_node_tier_review_round.py | test_a_remapped_500_records_one_sample_with_the_final_502 | 500 remapped 502 | test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[aigateway_http_401] |
| test_node_tier_review_round.py | test_inverted_caps_are_not_refused_because_the_hard_cap_already_wins | inverted caps | test_url4_executor.py::test_hard_cap_governs_even_when_knobs_are_inverted |
| test_node_tier_review_round.py | test_the_store_is_checked_before_the_world_is_built | store before world | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_review_round.py | test_the_package_does_not_re_export_the_private_tier_config | package API | N/A: the package is removed — DEC-4 test_no_module_imports_node_tier |
| test_node_tier_dispatch_fixes.py | test_a_retry_that_cannot_fit_the_deadline_is_not_started_and_the_caller_gets_502 | retry deadline | test_mount_routes.py::test_bound_elapsed_returns_504_and_stops_run |
| test_node_tier_dispatch_fixes.py | test_the_tier_binds_a_deadline_of_now_plus_the_request_budget | deadline binding | test_mount_routes.py::test_mount_call_publishes_direct_run_and_returns_200 (deadline_s == sync_max_wait_s + 5) |
| test_node_tier_dispatch_fixes.py | test_an_aigateway_401_answers_502_at_the_tier_with_its_code_kept | 401 → 502 | test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[aigateway_http_401] |
| test_node_tier_dispatch_fixes.py | test_a_500_with_a_url4_error_code_stays_500 | url4 500 stays | test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[internal_error] |
| test_node_tier_dispatch_fixes.py | test_a_500_with_a_downstream_code_becomes_502_and_keeps_code_and_message | downstream 502 | test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[provider_refused] |
| test_node_tier_dispatch_fixes.py | test_an_inner_app_that_sends_nothing_still_gets_a_500_envelope | silent inner app | N/A: no inner ASGI app; a run always ends in a terminal frame (lifecycle invariant), and a missing Result is 502 — test_mount_routes.py::test_a_success_without_its_result_frame_is_502_not_an_empty_200 |
| test_node_tier_dispatch_fixes.py | test_the_overload_503_carries_the_configured_retry_after | 503 Retry-After | test_mount_routes.py::test_admission_503_for_mount_calls |
| test_node_tier_dispatch_fixes.py | test_lifespan_shutdown_drains_readiness_to_503 | node shutdown | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_dispatch_fixes.py | test_drain_marks_readiness_not_ready_with_reason_draining | node drain | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately; worker drain: test_warm_pool.py::test_drain_kills_idle_warm_children_first |
| test_node_tier_dispatch_fixes.py | test_metrics_is_not_served_on_the_mount_port | metrics port | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_dispatch_fixes.py | test_the_sync_request_line_itself_carries_origin_sync_and_the_trace_id | sync log line | N/A: a mount call is a run; run logs are tested in the runner |
| test_node_tier_dispatch_fixes.py | test_the_duration_histogram_has_buckets_past_the_request_budget | node histogram | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_dispatch_fixes.py | test_a_built_tier_exposes_its_mounts_publicly | mounts public | test_direct_dispatch.py::test_describe_routes_lists_endpoints_and_data_routes; test_mount_routes.py::test_openapi_lists_every_mount_with_params_and_responses |
| test_node_tier_dispatch_fixes.py | test_a_bad_answer_seed_is_400_malformed_header | bad seed 400 | test_mount_routes.py::test_invalid_answer_seed_400 |
| test_node_tier_dispatch_fixes.py | test_two_overlapping_sync_requests_each_carry_their_own_identity | overlapping identity | test_mount_routes.py::test_two_concurrent_mount_calls_each_carry_their_own_identity |
| test_node_tier_build_fixes.py | test_the_node_hard_cap_default_is_64_mib_and_the_env_name_is_the_run_paths | hard cap default | N/A: the node's copy; the run path's hard cap (URL4_CLOUD_RESULT_HARD_CAP_BYTES) is the only one — test_url4_executor.py::test_result_over_hard_cap_fails_loudly_with_both_byte_counts |
| test_node_tier_build_fixes.py | test_the_new_settings_have_their_defaults_and_env_names | node settings | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_build_fixes.py | test_default_settings_validate | node settings | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_build_fixes.py | test_invalid_settings_are_refused_by_name | node settings | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_build_fixes.py | test_build_validates_settings_and_marks_readiness_failed | node settings | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_build_fixes.py | test_a_filesystem_store_from_the_env_is_refused | fs store refused | N/A: the App keeps the same refusal for runner=queue (app.py _build_artifact_reader; exercised by test_mount_direct_run_spine.py's own comment) |
| test_node_tier_build_fixes.py | test_an_s3_store_from_the_env_with_a_key_builds | s3 store builds | test_rest_artifacts.py::test_sync_result_response_serves_an_object_store_artifact |
| test_node_tier_build_fixes.py | test_an_empty_signing_key_is_refused_when_a_store_exists | empty key refused | N/A: the direct path serves an over-1-MiB result without a key (MC-D9) — test_mount_routes.py::test_no_signing_key_streams_artifact_200 |
| test_node_tier_build_fixes.py | test_a_store_construction_error_marks_readiness_failed_then_propagates | store error | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_build_fixes.py | test_a_spill_that_outlives_the_request_budget_still_redirects | late spill redirects | test_mount_routes.py::test_result_over_1mib_returns_signed_303 |
| test_node_tier_build_fixes.py | test_a_spill_over_its_own_bound_is_502_artifact_spill_failed | spill failure 502 | test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[artifact_spill_failed] |
| test_node_tier_build_fixes.py | test_a_spill_with_no_key_never_writes | no key | test_mount_routes.py::test_no_signing_key_streams_artifact_200 |
| test_node_tier_build_fixes.py | test_sigterm_drains_readiness_before_uvicorn_exits | node SIGTERM | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_tier_build_fixes.py | test_serve_starts_metrics_on_its_own_port_with_the_tier_registry | node metrics server | N/A: node-tier process machinery (its own settings/readiness/metrics port); the process is removed — the App and worker keep their own, tested separately |
| test_node_healthz_config_digest.py | test_the_node_healthz_reports_the_config_file_digest | digest | test_mount_routes.py::test_healthz_reports_the_mount_tables_config_digest |
| test_node_healthz_config_digest.py | test_an_unreadable_config_file_omits_the_digest | no digest | N/A: an unreadable config fails App startup now (the mount table is derived from it, C7) |
| test_node_healthz_config_digest.py | test_the_app_and_the_node_report_one_digest_for_one_file | one digest | test_mount_routes.py::test_healthz_reports_the_mount_tables_config_digest (one reporter left) |
| test_node_tier_spill.py | test_an_over_512kib_response_redirects_to_a_signed_artifact_location | 303 signed | test_mount_routes.py::test_result_over_1mib_returns_signed_303 (limit 1 MiB, ans:Q10) |
| test_node_tier_spill.py | test_the_signed_location_fetches_without_a_token_and_bare_is_refused | signed fetch | test_rest_artifacts.py::test_get_artifact_serves_complete_bytes_and_stays_refetchable; kind K4 |
| test_node_tier_spill.py | test_an_over_hard_cap_response_is_413_and_writes_nothing | hard cap 413 | test_url4_executor.py::test_result_over_hard_cap_fails_loudly_with_both_byte_counts; test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[result_too_large] |
| test_node_tier_spill.py | test_the_hard_cap_wins_even_when_the_caps_are_inverted | inverted | test_url4_executor.py::test_hard_cap_governs_even_when_knobs_are_inverted |
| test_node_tier_spill.py | test_a_spill_write_failure_is_502_and_never_returns_the_body_inline | write failure | test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table[artifact_spill_failed] |
| test_node_tier_spill.py | test_a_spill_with_no_signing_key_is_502_and_not_inline | no key | N/A: deliberate change (MC-D9): the body is streamed, and counted — test_mount_routes.py::test_no_signing_key_streams_artifact_200 |
| test_node_tier_spill.py | test_the_signing_key_is_read_from_the_deployment_env | key from env | N/A: the App reads URL4_CLOUD_ARTIFACT_SIGNING_KEY through Settings (config.py artifact_signing_key), as /artifacts already did |
| test_node_tier_spill.py | test_the_inline_cap_boundary_is_inclusive | inline boundary | test_artifact_spill_is_store_agnostic.py::test_the_cap_boundary_is_identical_on_object_storage |
| test_node_tier_spill.py | test_the_hard_cap_boundary_refuses_only_above | hard boundary | test_url4_executor.py::test_result_over_hard_cap_fails_loudly_with_both_byte_counts |
| test_node_tier_spill.py | test_a_small_body_still_returns_inline_unchanged | small inline | test_mount_routes.py::test_mount_call_publishes_direct_run_and_returns_200 |
| test_node_mount_route.py | test_a_known_path_is_a_full_match_carrying_the_app_as_endpoint | route match | test_mount_routes.py::test_mount_call_publishes_direct_run_and_returns_200 |
| test_node_mount_route.py | test_any_method_on_a_known_path_is_a_full_match | any method matches | test_mount_routes.py::test_a_wrong_method_on_a_mount_is_the_nodes_405_envelope |
| test_node_mount_route.py | test_an_unknown_path_is_no_match | unknown no match | test_mount_routes.py::test_eval_path_is_404_in_production |
| test_node_mount_route.py | test_a_websocket_scope_on_a_known_path_is_no_match | ws no match | N/A: mounts are FastAPI GET APIRoutes, which never match a websocket scope (framework behavior) |
| test_node_mount_route.py | test_the_path_set_is_read_at_match_time_not_at_construction | dynamic path set | N/A: mounts are registered once at startup (register_mounts) — test_mount_routes.py::test_openapi_never_cached_without_mounts |
| test_node_mount_route.py | test_the_match_is_on_the_route_path_under_a_root_path | root_path | N/A: APIRoute matching under root_path is framework behavior |
| test_node_mount_route.py | test_url_path_for_never_resolves | url_path_for | kept: test_node_mount_route.py::test_url_path_for_never_resolves (the file stays; NodeMountRoute serves local mode's eval path) |
| test_node_mount_route.py | test_install_appends_the_route_last | install last | N/A: NodeMountRoute ordering; mounts are exact-path routes guarded by F4 — test_world_mount_guard.py |
| test_node_mount_route.py | test_install_refuses_a_second_node_route | second node route | kept: test_node_mount_route.py::test_install_refuses_a_second_node_route (local mode's eval path) |
| test_node_mount_route.py | test_the_ordering_assertion_rejects_a_route_registered_after_the_node_route | ordering assertion | kept: test_node_mount_route.py::test_the_ordering_assertion_rejects_a_route_registered_after_the_node_route |
| test_node_mount_route.py | test_local_engine_paths_keep_the_engines_own_answer | local engine paths | test_local_mount_direct_run.py::test_local_mounts_use_inprocess_runner_and_openapi |
| test_node_mount_route.py | test_local_mount_and_eval_path_still_reach_the_node | local mount + eval | test_local_mount_direct_run.py::test_local_mounts_use_inprocess_runner_and_openapi (eval path: _LocalNodeMount, unchanged) |
| test_node_mount_route.py | test_a_wrong_method_on_a_local_mount_is_the_nodes_own_answer | local 405 | test_mount_routes.py::test_a_wrong_method_on_a_mount_is_the_nodes_405_envelope |
| test_node_mount_route.py | test_a_local_app_with_no_node_answers_every_path_as_the_engine | no node | N/A: local mode without a node world registers no mounts (register_mounts is called only after a node exists) |
| test_node_mount_route.py | test_the_local_app_installs_the_node_route_last | local route last | N/A: local keeps its eval-path NodeMountRoute unchanged |

### 2b. Other deleted tests (outside the 7 files)

The removal also deletes the forwarder's tests, three node-tier producer tests, and two node-tier
checks in shared test files. Each row maps them like the table above.

| file | test | behavior | direct-path test or N/A: reason |
|---|---|---|---|
| test_forwarder.py | test_forwarded_headers_strip_the_client_identity_and_set_the_verified_one | identity strip and reset | test_mount_routes.py::test_only_verified_identity_reaches_message; test_local_node_mount.py (local keeps `request_scope.forwarded_headers`) |
| test_forwarder.py | test_a_forged_identity_header_is_replaced_by_the_verified_value | forged identity replaced | test_mount_routes.py::test_only_verified_identity_reaches_message |
| test_forwarder.py | test_a_request_without_verified_identity_is_rejected_and_not_forwarded | no identity → 403 | test_mount_routes.py::test_missing_identity_403_nothing_queued |
| test_forwarder.py | test_the_forwarded_request_carries_path_and_query_unchanged | path and query unchanged | test_mount_routes.py::test_a_tilde_encoded_model_mount_is_served_with_its_target_unchanged |
| test_forwarder.py | test_an_unknown_path_404s_at_the_app_without_forwarding | unknown path 404 at the App | test_mount_routes.py::test_eval_path_is_404_in_production |
| test_forwarder.py | test_a_known_mount_is_forwarded | mount reaches the handler | test_mount_routes.py::test_mount_call_publishes_direct_run_and_returns_200 |
| test_forwarder.py | test_a_connection_error_is_retried_exactly_once | retry on connect error | N/A: no App → node hop; the run queue redelivers a lost run (kind K7) |
| test_forwarder.py | test_a_timeout_is_not_retried | no retry on timeout | N/A: no hop; a bound that passes is 504 and the run is stopped — test_mount_routes.py::test_bound_elapsed_returns_504_and_stops_run |
| test_forwarder.py | test_a_five_hundred_is_not_retried | no retry on 500 | N/A: no hop; a failed run answers once from its terminal frame — test_mount_routes.py::test_mount_status_mapping_matches_node_tier_table |
| test_forwarder.py | test_a_node_503_and_retry_after_pass_through_unmodified | 503 + Retry-After | test_mount_routes.py::test_admission_503_for_mount_calls |
| test_forwarder.py | test_node_down_is_503_with_retry_after_and_never_500 | node down → 503 | N/A: no node; no worker → the run waits in the queue until the bound, then 504 — test_mount_routes.py::test_bound_elapsed_returns_504_and_stops_run |
| test_forwarder.py | test_a_303_location_under_any_prefix_is_relayed_unchanged | 303 Location | test_mount_routes.py::test_result_over_1mib_returns_signed_303 |
| test_forwarder.py | test_a_303_location_is_unchanged_when_the_prefixes_match | 303 Location | test_mount_routes.py::test_result_over_1mib_returns_signed_303 |
| test_forwarder.py | test_healthz_reports_the_config_digest_when_the_forwarder_is_configured | healthz digest | test_mount_routes.py::test_healthz_reports_the_mount_tables_config_digest |
| test_forwarder.py | test_healthz_has_no_digest_without_a_forwarder | healthz without mounts | test_mount_routes.py::test_openapi_never_cached_without_mounts (no table → no digest); app.py healthz branch |
| test_forwarder.py | test_derive_forward_contract_reads_mounts_and_digest_from_the_world_file | mount set from the world file | test_mount_routes.py::test_healthz_reports_the_mount_tables_config_digest; integration/test_mount_direct_run_spine.py (`derive_mount_table`) |
| test_forwarder.py | test_derive_forward_contract_surfaces_a_config_error | config error surfaces | test_world_mount_guard.py::test_a_mount_shadowed_by_an_engine_route_fails_startup_naming_both |
| test_forwarder_wiring.py | test_install_forwarder_derives_the_mount_set_and_digest_at_startup | derive at startup | test_mount_routes.py::test_openapi_lists_every_mount_with_params_and_responses |
| test_forwarder_deployed_shape.py | test_engine_routes_reach_the_engine_and_mounts_reach_the_forwarder | engine vs mount routing | test_mount_routes.py::test_openapi_lists_every_mount_with_params_and_responses; test_mount_routes.py::test_a_mount_path_that_cannot_be_a_route_fails_registration |
| test_forwarder_deployed_shape.py | test_a_trailing_slash_and_a_wrong_method_keep_starlettes_answers | Starlette answers kept | test_node_mount_route.py::test_local_engine_paths_keep_the_engines_own_answer; mounts are plain FastAPI routes |
| test_forwarder_deployed_shape.py | test_a_wrong_method_on_a_mount_is_forwarded_for_the_node_to_answer | wrong method on a mount | test_mount_routes.py::test_a_wrong_method_on_a_mount_is_the_nodes_405_envelope |
| test_forwarder_deployed_shape.py | test_the_forward_client_bounds_connect_and_pool_at_two_seconds | 2 s connect budget | N/A: no App → node HTTP client exists |
| test_forwarder_deployed_shape.py | test_a_connect_or_pool_timeout_is_retried_once_then_answers_503 | connect retry then 503 | N/A: no hop; see test_admission_503_for_mount_calls for the 503 shape |
| test_forwarder_deployed_shape.py | test_a_connect_timeout_then_success_is_the_nodes_answer | retry then success | N/A: no hop; redelivery is kind K7 |
| test_forwarder_deployed_shape.py | test_a_read_or_write_timeout_is_504_and_never_retried | read timeout 504 | test_mount_routes.py::test_bound_elapsed_returns_504_and_stops_run |
| test_forwarder_deployed_shape.py | test_the_forward_budget_has_no_module_default | budget from settings only | N/A: the setting is removed (DEC-6 test_settings_no_node_fields.py); the bound is sync_max_wait_s |
| test_forwarder_deployed_shape.py | test_install_forwarder_takes_the_budget_from_settings | budget from settings | test_mount_routes.py::test_mount_call_publishes_direct_run_and_returns_200 (deadline_s from sync_max_wait_s) |
| test_forwarder_deployed_shape.py | test_a_303_is_relayed_with_its_location_unchanged | 303 relayed | test_mount_routes.py::test_result_over_1mib_returns_signed_303 |
| test_forwarder_deployed_shape.py | test_the_prefix_rewrite_is_gone | no prefix rewrite | N/A: no relay; the App builds the Location itself (signed_artifact_path) |
| test_forwarder_deployed_shape.py | test_the_nodes_server_and_date_headers_are_not_relayed | no duplicate server/date | N/A: no relayed response; the App writes its own headers once |
| test_forwarder_deployed_shape.py | test_the_forwarder_keeps_no_config_digest_and_takes_no_mount_set_at_construction | forwarder state shape | N/A: the forwarder is deleted |
| test_forwarder_deployed_shape.py | test_install_forwarder_lives_beside_the_forwarder | module layout | N/A: the forwarder is deleted; test_layering_node_tier_removed.py pins that nothing imports it |
| test_forwarder_deployed_shape.py | test_a_filesystem_store_is_refused_when_a_node_tier_is_configured | FX-38 fs store refused | N/A: no node pod; the queue runner refusal stays — test_artifact_storage_selection.py::test_a_queue_app_left_on_filesystem_storage_refuses_to_boot |
| test_forwarder_deployed_shape.py | test_a_filesystem_store_is_still_fine_without_a_node_tier | fs store without node | test_artifact_storage_selection.py::test_a_local_app_still_uses_the_filesystem |
| test_scope_producers.py | test_the_node_tier_binds_the_scope_and_the_trace_before_the_handler_runs | producer binds scope + trace | test_scope_producers.py::test_the_run_path_binds_the_scope_before_the_handler_runs (a direct run is a run); test_scope_producers.py::test_the_local_sync_mount_binds_the_scope_and_the_trace_before_the_handler_runs |
| test_scope_producers.py | test_the_node_tier_binds_no_trace_for_a_malformed_traceparent | malformed traceparent | test_scope_producers.py::test_the_local_sync_mount_binds_no_trace_when_the_caller_sent_none |
| test_scope_producers.py | test_a_node_tier_mount_call_reaches_aigateway_with_the_callers_identity_and_trace | identity + trace reach aigateway | test_scope_producers.py::test_the_run_path_binds_the_scope_before_the_handler_runs (identity from job env); test_mount_routes.py::test_only_verified_identity_reaches_message |
| test_world_run_log_namespace.py | test_building_the_node_tier_writes_no_run_line | no run log line at build | N/A: the node tier build is deleted; test_world_run_log_namespace.py::test_each_local_run_on_the_shared_node_writes_its_own_line keeps the rule for the shared node |
| test_wire_envelope.py | test_the_node_tier_builds_no_envelope_by_hand | one envelope writer | test_wire_envelope.py::test_the_mount_surfaces_build_no_envelope_by_hand |
| test_chart_render_node_tier.py | (every test) | node chart objects | N/A: the node chart objects are deleted; the signing-secret tests that still apply moved to test_chart_render_artifact_signing.py; DEC-2 test_chart_node_tier_removed.py |

Result: PASS

## 3. The kind suite is green, including the chaos cases

Evidence (2026-09-27): `pytest tests/kind -m kind -v` against `deploy/kind/up.sh` — 13 passed in
258 s: K1, K2, K3, K6, K12, K4, K5, K7, MNT-26, K8, K9, K10, K11 (chaos cases included: pod kill,
OOM, rollout restart, NATS restart, drained upgrade). The run found F7–F11 and five harness
defects first; each is fixed (implementation-notes.md, "F7–F11").

Result: PASS

## 4. The measurement report exists and compares the node-tier mount call with the direct run

Evidence: `2026-09-26-B1.md` (node tier) and `2026-09-26-B4.md` (direct run, warm children),
the same target `/anthropic/claude-haiku-4-5?q=('hi')!'go'` on the kind environment, stub
latency 200 ms, 300 requests per phase. Report only — latency gates nothing (ans:Q3).

| Case | Sequential p50 / p95 ms | Concurrency 8 p50 / p95 ms | Errors at concurrency 8 |
|---|---|---|---|
| B1 node tier | 204.9 / 210.8 | 207.5 / 210.1 (n=2) | 298 of 300 shed with 503 (per-pod admission cap) |
| B4 direct run | 1518.8 / 3986.2 | 5297.2 / 7555.3 | 0 |

Reading: the node tier answers a single call in ~5 ms over the stub, but sheds almost all
concurrent calls; the direct run answers every call, and its extra time is the queue claim
(F6: 0–5 s while the queue is idle, not fixed here) plus the hand-off. B4 was measured before
F8–F11. B2/B3 (`GET /?q=`, no model call) are in this directory for the cold/warm comparison.

Result: PASS

## 5. No environment outside the repo sets `node.enabled: true`

Evidence (2026-09-26): the owner named `OpenMined/infrastructure` as the place the deployments
are configured. Inspected at `d7fbd9f`:

- `kubernetes/tenants/screamingface/charts/url4-cloud{,-staging,-prod}.yaml` deploy this chart
  (`apps/screamingface-engine/deploy/helm`) with `kubernetes/apps/sf-url4-cloud/values/{dev,staging,prod}.yaml`.
  None of the three has a `node:` key (parsed as YAML; top-level keys listed), and none sets
  `artifactSigning`.
- The PR previews (`kubernetes/appsets/screamingface-previews.yaml` →
  `kubernetes/apps/sf-preview/templates/workload-application.yaml`) pass inline values with no
  `node:` key and no Helm `parameters` under `node.`.
- The whole repo has no match for `node.enabled`, `node tier`, `node-tier`, `url4-cloud-node`,
  `NODE_BASE_URL` or `node_sync`.
- The chart after the removal renders with each of the three values files (14 objects each, no
  `-node` object).

Sizing decision (owner, 2026-09-26): the new chart defaults match what these environments run
today, so none of the three values files changes. `events.maxBytes` defaults to 1 GiB (today's
per-run streams reserved 50 MB each, and 2 pods × 4 slots run at most 8 at once: ~400 MB),
`events.replicas` stays 1 although NATS runs 3 nodes there (no replicated events store yet), and
`runnerPool.warmChildren` defaults to 2 per pod (two idle children fit a 4-slot pod's memory
request; the third and fourth concurrent run on a pod pay a cold boot). Rendered:
all three get `EVENTS_MAX_BYTES=1073741824`, `EVENTS_REPLICAS=1`, `WORKER_WARM_CHILDREN=2`. The PR
preview (512 Mi JetStream store) is out of scope by the owner's choice.

Result: PASS
