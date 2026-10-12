import Url4Rds.Binding

/-!
# The execution gate and the call count

Spec C §12.2 (quorum), §10.1 (`;required` / `;optional`), §13.6 (expression failure),
Spec B §6.1.2 (broadcast executes once per *resolved* source).

* `gate_eq_false_of_required_failed` — quorum cannot override a failed required source;
* `gate_mono` — more successes never close the gate (quorum is a quality floor);
* `gate_all_of_all_optional` — `quorum=all` with no required source always passes,
  so an all-optional group whose sources all failed runs with no inputs;
* `length_calls_*` — exactly one call per aggregate group, one per resolved source
  under broadcast, none when the gate is closed.
-/

namespace Url4Rds

variable {N W V : Type}

/-- Spec C §12.2 quorum values. -/
inductive Quorum where
  | all
  | atLeast (n : Nat)
  | majority

/-- Every `;required` source resolved. -/
def requiredOk (S : List (Source N W V)) : Bool :=
  S.all (fun s => !s.required || s.resolved)

/-- The quorum test. `all` adds nothing to `requiredOk` (Spec C §12.2: "All `;required`
sources must resolve"); `majority` counts the post-expansion total, `floor(T/2)+1`. -/
def quorumOk : Quorum → List (Source N W V) → Bool
  | .all, _ => true
  | .atLeast n, S => n ≤ resolvedCount S
  | .majority, S => S.length / 2 + 1 ≤ resolvedCount S

def gate (q : Quorum) (S : List (Source N W V)) : Bool :=
  requiredOk S && quorumOk q S

theorem gate_eq_false_of_required_failed (q : Quorum) {S : List (Source N W V)}
    {s : Source N W V} (hs : s ∈ S) (hr : s.required = true) (hf : s.resolved = false) :
    gate q S = false := by
  have : requiredOk S = false := by
    unfold requiredOk
    rw [List.all_eq_false]
    exact ⟨s, hs, by simp [hr, hf]⟩
  simp [gate, this]

theorem gate_all_of_all_optional {S : List (Source N W V)}
    (h : ∀ s ∈ S, s.required = false) : gate .all S = true := by
  simp only [gate, quorumOk, Bool.and_true, requiredOk, List.all_eq_true]
  intro s hs
  simp [h s hs]

/-! ## Monotonicity -/

/-- `T` is `S` with possibly more sources resolved; flags and order are unchanged. -/
inductive Improves : List (Source N W V) → List (Source N W V) → Prop where
  | nil : Improves [] []
  | cons {s t : Source N W V} {ss ts : List (Source N W V)} :
      s.required = t.required → (s.resolved = true → t.resolved = true) →
      Improves ss ts → Improves (s :: ss) (t :: ts)

theorem Improves.length_eq {S T : List (Source N W V)} (h : Improves S T) :
    S.length = T.length := by
  induction h with
  | nil => rfl
  | cons _ _ _ ih => simp [ih]

theorem Improves.resolvedCount_le {S T : List (Source N W V)} (h : Improves S T) :
    resolvedCount S ≤ resolvedCount T := by
  induction h with
  | nil => exact Nat.le_refl 0
  | @cons s t ss ts _ hres _ ih =>
    rw [resolvedCount_cons, resolvedCount_cons]
    cases hs : s.resolved
    · cases t.resolved <;> simp <;> omega
    · simp [hres hs]
      omega

theorem Improves.requiredOk {S T : List (Source N W V)} (h : Improves S T)
    (hS : requiredOk S = true) : requiredOk T = true := by
  induction h with
  | nil => rfl
  | @cons s t ss ts hreq hres _ ih =>
    simp only [Url4Rds.requiredOk, List.all_cons, Bool.and_eq_true] at hS ⊢
    refine ⟨?_, ih hS.2⟩
    cases hr : t.required
    · rfl
    · have hs : s.resolved = true := by
        have := hS.1
        rw [hreq, hr] at this
        simpa using this
      simp [hres hs]

theorem gate_mono (q : Quorum) {S T : List (Source N W V)} (h : Improves S T)
    (hS : gate q S = true) : gate q T = true := by
  simp only [gate, Bool.and_eq_true] at hS ⊢
  refine ⟨h.requiredOk hS.1, ?_⟩
  have hc := h.resolvedCount_le
  have hl := h.length_eq
  cases q with
  | all => rfl
  | atLeast n =>
    have := hS.2
    simp only [quorumOk, decide_eq_true_eq] at this ⊢
    omega
  | majority =>
    have := hS.2
    simp only [quorumOk, decide_eq_true_eq] at this ⊢
    omega

/-! ## The call count -/

/-- One code-pointer call. -/
structure Call (N W V : Type) where
  inputs : List (Input N W V)

/-- The calls a group makes: none when the gate is closed; one with every bound input
(`!`); or, for broadcast (`!*`), one per resolved source. A broadcast call gets its own
source first (`$current`), then every other resolved source that a `$`-reference in
the pointer names (`refs`, by position; Spec B §6.1.2 rules 3–4). -/
def calls (broadcast : Bool) (refs : Nat → Bool) (q : Quorum) (S : List (Source N W V)) :
    List (Call N W V) :=
  if gate q S then
    if broadcast then
      (bind S).map fun i => ⟨i :: (bind S).filter fun j => refs j.pos && j.pos != i.pos⟩
    else [⟨bind S⟩]
  else []

theorem calls_eq_nil_of_gate_false (b : Bool) (refs : Nat → Bool) (q : Quorum)
    (S : List (Source N W V)) (h : gate q S = false) : calls b refs q S = [] := by
  simp [calls, h]

theorem calls_aggregate (refs : Nat → Bool) (q : Quorum) (S : List (Source N W V))
    (h : gate q S = true) : calls false refs q S = [⟨bind S⟩] := by
  simp [calls, h]

theorem length_calls_broadcast (refs : Nat → Bool) (q : Quorum) (S : List (Source N W V))
    (h : gate q S = true) : (calls true refs q S).length = resolvedCount S := by
  simp [calls, h, length_bind]

/-- Every broadcast call starts with its own resolved source (`$current`). -/
theorem head?_inputs_of_mem_calls_broadcast (refs : Nat → Bool) (q : Quorum)
    (S : List (Source N W V)) (c : Call N W V) (hc : c ∈ calls true refs q S) :
    ∃ i ∈ bind S, c.inputs.head? = some i := by
  unfold calls at hc
  split at hc
  · simp only [↓reduceIte, List.mem_map] at hc
    obtain ⟨i, hi, rfl⟩ := hc
    exact ⟨i, hi, rfl⟩
  · simp at hc

/-- With no `$`-reference in the pointer, each broadcast call has exactly one input. -/
theorem length_inputs_of_mem_calls_broadcast (q : Quorum) (S : List (Source N W V))
    (c : Call N W V) (hc : c ∈ calls true (fun _ => false) q S) : c.inputs.length = 1 := by
  unfold calls at hc
  split at hc
  · simp only [↓reduceIte, List.mem_map] at hc
    obtain ⟨i, _, rfl⟩ := hc
    simp
  · simp at hc

end Url4Rds
