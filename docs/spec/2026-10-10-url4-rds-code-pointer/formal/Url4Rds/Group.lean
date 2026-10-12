import Url4Rds.Gate
import Url4Rds.Status

/-!
# One RDS group, end to end

`evalGroup` is the order of checks for an aggregate group `(S)!pointer` whose pointer
text has no `$`-reference (a `$` pointer is looked up at call time, after its sources):

1. **Capability.** The node cannot run this pointer form (a `url4://` or absolute URI,
   or no code port) → `unsupported_mode`, and *no source starts*.
2. **Preflight.** The pointer is not mounted as code → `intent_error`, and *no source
   starts* (`evalGroup_unmounted`). An expression that cannot run does not pay for its
   sources.
3. **Required.** A failed `;required` source fails the group (Spec C §13.6 rule 1).
4. **Quorum.** An unmet quorum fails the group (Spec C §13.6 rule 2).
5. **Execute.** The executor gets exactly `bind S` (`evalGroup_exec`). Every execution
   failure is `intent_error`, permanent (Spec C §13.6 rule 3: "the error code is
   `intent_error`"); a handler's own URL4 code is kept only as detail.

The model records "no source starts" as the `Bool` in the result: `resolve` is called
only when it is `true`. That `resolve` is never *evaluated* in the `false` branches is
true by definition here; the Python preflight test (row 17) checks it on real I/O.
-/

namespace Url4Rds

variable {N W V R : Type}

/-- What the executor (the mounted handler) returns. -/
inductive ExecResult (R : Type) where
  | ok (r : R)
  /-- The handler raised a URL4 error with its own code. -/
  | url4Error (c : Code)
  /-- The handler raised anything else, or returned a value of the wrong type. -/
  | crash

inductive Failure where
  | unsupportedMode
  /-- `intent_error`; `detail` keeps a handler's own code. -/
  | intentError (detail : Option Code)
  | requiredSourceFailed
  | quorumNotMet
  deriving DecidableEq, Repr

inductive Outcome (R : Type) where
  | value (r : R)
  | failed (f : Failure)

def ExecResult.toOutcome : ExecResult R → Outcome R
  | .ok r => .value r
  | .url4Error c => .failed (.intentError (some c))
  | .crash => .failed (.intentError none)

/-- The group's outcome and whether its sources were started. -/
def evalGroup (supported mounted : Bool) (q : Quorum) (resolve : Unit → List (Source N W V))
    (exec : List (Input N W V) → ExecResult R) : Outcome R × Bool :=
  if !supported then (.failed .unsupportedMode, false)
  else if !mounted then (.failed (.intentError none), false)
  else
    let S := resolve ()
    if requiredOk S = false then (.failed .requiredSourceFailed, true)
    else if quorumOk q S = false then (.failed .quorumNotMet, true)
    else ((exec (bind S)).toOutcome, true)

theorem evalGroup_unsupported (m : Bool) (q : Quorum) (resolve : Unit → List (Source N W V))
    (exec : List (Input N W V) → ExecResult R) :
    evalGroup false m q resolve exec = (.failed .unsupportedMode, false) :=
  rfl

theorem evalGroup_unmounted (q : Quorum) (resolve : Unit → List (Source N W V))
    (exec : List (Input N W V) → ExecResult R) :
    evalGroup true false q resolve exec = (.failed (.intentError none), false) :=
  rfl

/-- When the gate is open, the executor receives exactly the bound inputs. -/
theorem evalGroup_exec (q : Quorum) (resolve : Unit → List (Source N W V))
    (exec : List (Input N W V) → ExecResult R) (h : gate q (resolve ()) = true) :
    evalGroup true true q resolve exec = ((exec (bind (resolve ()))).toOutcome, true) := by
  simp only [gate, Bool.and_eq_true] at h
  simp [evalGroup, h.1, h.2]

/-- A closed gate never reaches the executor. -/
theorem evalGroup_ne_exec_of_gate_false (q : Quorum)
    (resolve : Unit → List (Source N W V)) (exec : List (Input N W V) → ExecResult R)
    (h : gate q (resolve ()) = false) :
    ∃ f, evalGroup true true q resolve exec = (.failed f, true) ∧
      (f = .requiredSourceFailed ∨ f = .quorumNotMet) := by
  unfold gate at h
  cases hr : requiredOk (resolve ()) with
  | false => exact ⟨.requiredSourceFailed, by simp [evalGroup, hr], Or.inl rfl⟩
  | true =>
    have hq : quorumOk q (resolve ()) = false := by simpa [hr] using h
    exact ⟨.quorumNotMet, by simp [evalGroup, hr, hq], Or.inr rfl⟩

/-- Every execution failure is `intent_error` (Spec C §13.6 rule 3). -/
theorem exists_intentError_of_toOutcome_eq_failed (e : ExecResult R) (f : Failure) :
    e.toOutcome = .failed f → ∃ d, f = .intentError d := by
  cases e with
  | ok r => intro h; cases h
  | url4Error c => intro h; cases h; exact ⟨some c, rfl⟩
  | crash => intro h; cases h; exact ⟨none, rfl⟩

end Url4Rds
