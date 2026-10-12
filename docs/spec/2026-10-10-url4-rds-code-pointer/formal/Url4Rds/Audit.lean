import Lean
import Url4Rds.Intent
import Url4Rds.Binding
import Url4Rds.Gate
import Url4Rds.Expansion
import Url4Rds.Status
import Url4Rds.Group

/-!
# Axiom audit

`#assert_axioms` fails the build when a listed theorem depends on `sorryAx` or on any
axiom outside `propext`, `Classical.choice`, `Quot.sound`. The check asks the kernel,
so a clean-looking theorem that uses an unproved helper still fails.
-/

open Lean Elab Command in
elab "#assert_axioms " ids:ident* : command => do
  let allowed := [``propext, ``Classical.choice, ``Quot.sound]
  for id in ids do
    let n ← liftCoreM <| realizeGlobalConstNoOverloadWithInfo id
    let axs ← collectAxioms n
    for a in axs do
      unless allowed.contains a do
        throwError "{n} depends on axiom {a}"

#assert_axioms
  Url4Rds.target_conformant
  Url4Rds.v1_not_conforms_iff
  Url4Rds.v1_act_eq_invokeLocal_iff
  Url4Rds.v1_act_eq_target_act
  Url4Rds.v1_strictFields_iff
  Url4Rds.specMode_eq_rds_of_strictFields
  Url4Rds.length_bind
  Url4Rds.find?_pos_bind
  Url4Rds.payload_bind_reweigh
  Url4Rds.pairwise_pos_bind
  Url4Rds.gate_eq_false_of_required_failed
  Url4Rds.gate_all_of_all_optional
  Url4Rds.gate_mono
  Url4Rds.calls_eq_nil_of_gate_false
  Url4Rds.calls_aggregate
  Url4Rds.length_calls_broadcast
  Url4Rds.head?_inputs_of_mem_calls_broadcast
  Url4Rds.length_inputs_of_mem_calls_broadcast
  Url4Rds.resolvedCount_expandWith_expand
  Url4Rds.unnamed_expansions_collide
  Url4Rds.cls_inbound_statusOf
  Url4Rds.inbound_statusOf
  Url4Rds.inbound_400_ne_unsupported_mode
  Url4Rds.cls_inbound_500_ne_cls_intentError
  Url4Rds.evalGroup_unsupported
  Url4Rds.evalGroup_unmounted
  Url4Rds.evalGroup_exec
  Url4Rds.evalGroup_ne_exec_of_gate_false
  Url4Rds.exists_intentError_of_toOutcome_eq_failed
