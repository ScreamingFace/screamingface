/-!
# Input binding

Spec A §1.1: in RDS mode a node binds the resolved source data to the code's input
contract; variable references (`$name`, `$N`) are the parameter mapping. Spec B §6.2:
`$N` is the 1-based source position; named and positional references coexist.

The model binds a source list to a list of `Input`s. Each input keeps its source
position, name and weight. The theorems are the delivery contract:

* `find?_pos_bind` — the input at position `p` holds exactly the resolved value of
  source `p`, and a failed source has no input (no `null`, no placeholder);
* `payload_bind_reweigh` — delivery does not depend on weights (a weight-`0.0` source
  is delivered: weight is attribution, Spec B §5.3.10.3);
* `pairwise_pos_bind` — inputs are in source order;
* `length_bind` — one input per resolved source.
-/

namespace Url4Rds

variable {N W W' V : Type}

/-- A source after it reached a terminal state. -/
structure Source (N W V : Type) where
  name : Option N
  weight : Option W
  required : Bool
  /-- `some v`: resolved to `v`; `none`: failed or timed out. -/
  outcome : Option V

/-- One bound input of a code-pointer call. -/
structure Input (N W V : Type) where
  pos : Nat
  name : Option N
  weight : Option W
  value : V

def Source.resolved (s : Source N W V) : Bool :=
  s.outcome.isSome

/-- Bind sources to inputs; `k` is the position of the first source. -/
def bindFrom : Nat → List (Source N W V) → List (Input N W V)
  | _, [] => []
  | k, s :: ss =>
    match s.outcome with
    | some v => ⟨k, s.name, s.weight, v⟩ :: bindFrom (k + 1) ss
    | none => bindFrom (k + 1) ss

/-- Positions are 1-based (Spec B §6.2). -/
def bind (S : List (Source N W V)) : List (Input N W V) :=
  bindFrom 1 S

def resolvedCount (S : List (Source N W V)) : Nat :=
  (S.filter Source.resolved).length

@[simp] theorem resolvedCount_nil : resolvedCount ([] : List (Source N W V)) = 0 :=
  rfl

theorem resolvedCount_cons (s : Source N W V) (ss : List (Source N W V)) :
    resolvedCount (s :: ss) = (if s.resolved then 1 else 0) + resolvedCount ss := by
  unfold resolvedCount
  cases h : s.resolved <;> simp [h] <;> omega

@[simp] theorem bindFrom_nil (k : Nat) : bindFrom k ([] : List (Source N W V)) = [] :=
  rfl

theorem bindFrom_cons_some (k : Nat) (s : Source N W V) (ss : List (Source N W V)) (v : V)
    (h : s.outcome = some v) :
    bindFrom k (s :: ss) = ⟨k, s.name, s.weight, v⟩ :: bindFrom (k + 1) ss := by
  simp [bindFrom, h]

theorem bindFrom_cons_none (k : Nat) (s : Source N W V) (ss : List (Source N W V))
    (h : s.outcome = none) :
    bindFrom k (s :: ss) = bindFrom (k + 1) ss := by
  simp [bindFrom, h]

/-! ## One input per resolved source -/

theorem length_bindFrom (k : Nat) (S : List (Source N W V)) :
    (bindFrom k S).length = resolvedCount S := by
  induction S generalizing k with
  | nil => rfl
  | cons s ss ih =>
    rw [resolvedCount_cons]
    cases h : s.outcome with
    | none =>
      rw [bindFrom_cons_none k s ss h, ih]
      simp [Source.resolved, h]
    | some v =>
      rw [bindFrom_cons_some k s ss v h, List.length_cons, ih]
      simp [Source.resolved, h]
      omega

theorem length_bind (S : List (Source N W V)) : (bind S).length = resolvedCount S :=
  length_bindFrom 1 S

/-! ## Value fidelity and absence -/

/-- The input at position `p` holds the resolved value of source `p`; a failed source
(or a position outside the list) has no input. -/
theorem find?_pos_bindFrom (k p : Nat) (S : List (Source N W V)) :
    ((bindFrom k S).find? (fun i => i.pos == p)).map Input.value =
      if k ≤ p then (S[p - k]?).bind Source.outcome else none := by
  induction S generalizing k with
  | nil => simp
  | cons s ss ih =>
    cases h : s.outcome with
    | none =>
      rw [bindFrom_cons_none k s ss h, ih]
      by_cases hkp : k = p
      · subst hkp
        have hnot : ¬ (k + 1 ≤ k) := by omega
        simp [h, hnot]
      · by_cases hle : k ≤ p
        · have hsucc : k + 1 ≤ p := by omega
          have hidx : p - k = (p - (k + 1)) + 1 := by omega
          simp [hsucc, hle, hidx]
        · have hnot : ¬ (k + 1 ≤ p) := by omega
          simp [hnot, hle]
    | some v =>
      rw [bindFrom_cons_some k s ss v h]
      by_cases hkp : k = p
      · subst hkp
        simp [h]
      · have hne : (k == p) = false := by simp [hkp]
        rw [List.find?_cons, hne]
        simp only
        rw [ih]
        by_cases hle : k ≤ p
        · have hsucc : k + 1 ≤ p := by omega
          have hidx : p - k = (p - (k + 1)) + 1 := by omega
          simp [hsucc, hle, hidx]
        · have hnot : ¬ (k + 1 ≤ p) := by omega
          simp [hnot, hle]

theorem find?_pos_bind (p : Nat) (S : List (Source N W V)) :
    ((bind S).find? (fun i => i.pos == p)).map Input.value =
      if 1 ≤ p then (S[p - 1]?).bind Source.outcome else none :=
  find?_pos_bindFrom 1 p S

/-! ## Weight does not filter delivery -/

/-- Change a source's weight (for example to `0.0`, or remove it). -/
def Source.reweigh (f : Option W → Option W') (s : Source N W V) : Source N W' V :=
  ⟨s.name, f s.weight, s.required, s.outcome⟩

/-- What the code receives, without the attribution metadata. -/
def Input.payload (i : Input N W V) : Nat × Option N × V :=
  (i.pos, i.name, i.value)

theorem payload_bindFrom_reweigh (f : Option W → Option W') (k : Nat)
    (S : List (Source N W V)) :
    (bindFrom k (S.map (Source.reweigh f))).map Input.payload =
      (bindFrom k S).map Input.payload := by
  induction S generalizing k with
  | nil => rfl
  | cons s ss ih =>
    cases h : s.outcome with
    | none =>
      have h' : (s.reweigh f).outcome = none := h
      rw [List.map_cons, bindFrom_cons_none k _ _ h', bindFrom_cons_none k s ss h, ih]
    | some v =>
      have h' : (s.reweigh f).outcome = some v := h
      rw [List.map_cons, bindFrom_cons_some k _ _ v h', bindFrom_cons_some k s ss v h]
      simp only [List.map_cons, ih]
      rfl

theorem payload_bind_reweigh (f : Option W → Option W') (S : List (Source N W V)) :
    (bind (S.map (Source.reweigh f))).map Input.payload = (bind S).map Input.payload :=
  payload_bindFrom_reweigh f 1 S

/-! ## Source order -/

theorem le_pos_of_mem_bindFrom {k : Nat} {S : List (Source N W V)} {i : Input N W V}
    (hi : i ∈ bindFrom k S) : k ≤ i.pos := by
  induction S generalizing k with
  | nil => simp at hi
  | cons s ss ih =>
    cases h : s.outcome with
    | none =>
      rw [bindFrom_cons_none k s ss h] at hi
      have := ih hi
      omega
    | some v =>
      rw [bindFrom_cons_some k s ss v h, List.mem_cons] at hi
      rcases hi with rfl | hi
      · exact Nat.le_refl _
      · have := ih hi
        omega

theorem pairwise_pos_bindFrom (k : Nat) (S : List (Source N W V)) :
    (bindFrom k S).Pairwise (fun a b => a.pos < b.pos) := by
  induction S generalizing k with
  | nil => exact List.Pairwise.nil
  | cons s ss ih =>
    cases h : s.outcome with
    | none =>
      rw [bindFrom_cons_none k s ss h]
      exact ih (k + 1)
    | some v =>
      rw [bindFrom_cons_some k s ss v h]
      refine List.Pairwise.cons ?_ (ih (k + 1))
      intro b hb
      have := le_pos_of_mem_bindFrom hb
      show k < b.pos
      omega

theorem pairwise_pos_bind (S : List (Source N W V)) :
    (bind S).Pairwise (fun a b => a.pos < b.pos) :=
  pairwise_pos_bindFrom 1 S

end Url4Rds
