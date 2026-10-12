/-!
# Error codes and HTTP status

Spec C §13.2.1 maps an inbound HTTP status to an error code and class. A node that
answers over HTTP chooses a status for each of its own codes. The rule this model
checks: a caller that applies §13.2.1 to our status must recover the *class* of our
code (so it does not retry a permanent failure), and the code itself when §13.2.1
has a status for it.

`status_unsupported_mode_is_501` and `inbound_400_ne_unsupported_mode` show why
`unsupported_mode` must be 501, not 400. `intent_error` has no status in §13.2.1; 422
keeps its class (permanent) and the body carries the code (§13.2.1 "Response body
inspection").

`Code.other c` stands for every other code of class `c` (for example `quorum_not_met`,
`expansion_not_iterable`, or a transient resolution failure). The rule for them is the
class default: permanent → 422, transient → 502.
-/

namespace Url4Rds

inductive Cls where
  | transient
  | permanent
  deriving DecidableEq, Repr

inductive Code where
  | malformedSource
  | unsupportedMode
  | intentError
  | internalError
  | sourceNotFound
  | timeout
  | unavailable
  /-- Any other code, by its class. -/
  | other (c : Cls)
  deriving DecidableEq, Repr

/-- Spec C §13.5.2 default classes. -/
def Code.cls : Code → Cls
  | .malformedSource | .unsupportedMode | .intentError | .sourceNotFound => .permanent
  | .internalError | .timeout | .unavailable => .transient
  | .other c => c

/-- Spec C §13.2.1, inbound side (the rows this change touches; unmapped 4xx →
`malformed_source`, unmapped 5xx → `internal_error`). -/
def inbound : Nat → Code
  | 400 => .malformedSource
  | 404 => .sourceNotFound
  | 422 => .malformedSource
  | 500 => .internalError
  | 501 => .unsupportedMode
  | 502 => .unavailable
  | 503 => .unavailable
  | 504 => .timeout
  | n => if n < 500 then .malformedSource else .internalError

/-- The status this spec assigns to each code it can raise over HTTP. -/
def statusOf : Code → Nat
  | .malformedSource => 400
  | .unsupportedMode => 501
  | .intentError => 422
  | .internalError => 500
  | .sourceNotFound => 404
  | .timeout => 504
  | .unavailable => 503
  | .other .permanent => 422
  | .other .transient => 502

/-- Every code keeps its class through Spec C §13.2.1. -/
theorem cls_inbound_statusOf (c : Code) : (inbound (statusOf c)).cls = c.cls := by
  cases c with
  | other k => cases k <;> decide
  | _ => decide

/-- Every named code except `intent_error` keeps its exact code. -/
theorem inbound_statusOf (c : Code) (h : c ≠ .intentError) (ho : ∀ k, c ≠ .other k) :
    inbound (statusOf c) = c := by
  cases c with
  | intentError => exact absurd rfl h
  | other k => exact absurd rfl (ho k)
  | _ => decide

theorem status_unsupported_mode_is_501 : statusOf .unsupportedMode = 501 :=
  rfl

/-- 400 would turn `unsupported_mode` into `malformed_source` at a conformant caller. -/
theorem inbound_400_ne_unsupported_mode : inbound 400 ≠ .unsupportedMode := by
  decide

/-- 500 would turn the permanent `intent_error` into a transient (retried) error. -/
theorem cls_inbound_500_ne_cls_intentError :
    (inbound 500).cls ≠ Code.intentError.cls := by
  decide

end Url4Rds
