import Url4Rds.Binding

/-!
# Source expansion (`*source` / `;expand`)

Spec B §5.3.12.4: each element becomes an independent source at the position of the
expansion source, and positions are renumbered. §5.3.12.5: elements are named
`name[i]`, or `src[i]` for an unnamed expansion. §5.3.12.7: quorum counts the
post-expansion sources.

The model expands *before* binding, so `bind` numbers the inputs after expansion
(`$N` is the post-expansion position) and the gate sees the post-expansion count.

`unnamed_expansions_collide` shows that the spec's naming rule is not injective:
two unnamed expansions both produce `src[0]`. Names therefore cannot be the only key
of the input contract; positions are (open question Q4).
-/

namespace Url4Rds

variable {N W V : Type}

/-- A source-list entry before expansion. A failed expansion source is one failed
source; Spec C §10.2.1: a non-iterable value fails with `expansion_not_iterable`. -/
inductive Entry (N W V : Type) where
  | single (s : Source N W V)
  | expand (name : Option N) (weight : Option W) (required : Bool)
      (elems : Option (List V))

/-- Element names; `idx none i` is `src[i]`, `idx (some n) i` is `n[i]`. -/
def Entry.expandWith (idx : Option N → Nat → N) : Entry N W V → List (Source N W V)
  | .single s => [s]
  | .expand name weight required none => [⟨name, weight, required, none⟩]
  | .expand name weight required (some vs) =>
    (List.range vs.length).zip vs |>.map fun (i, v) =>
      ⟨some (idx name i), weight, required, some v⟩

def expandAll (idx : Option N → Nat → N) (E : List (Entry N W V)) : List (Source N W V) :=
  E.flatMap (Entry.expandWith idx)

theorem length_expandWith_expand (idx : Option N → Nat → N) (name : Option N)
    (w : Option W) (r : Bool) (vs : List V) :
    (Entry.expandWith idx (.expand name w r (some vs))).length = vs.length := by
  simp [Entry.expandWith]

/-- Every element of a resolved expansion is a resolved source, so an expansion of `n`
elements adds `n` to the quorum count (Spec B §5.3.12.7). -/
theorem resolvedCount_expandWith_expand (idx : Option N → Nat → N) (name : Option N)
    (w : Option W) (r : Bool) (vs : List V) :
    resolvedCount (Entry.expandWith idx (.expand name w r (some vs))) = vs.length := by
  unfold resolvedCount
  rw [List.filter_eq_self.mpr]
  · exact length_expandWith_expand idx name w r vs
  · intro s hs
    simp only [Entry.expandWith, List.mem_map] at hs
    obtain ⟨⟨i, v⟩, _, rfl⟩ := hs
    rfl

/-- Two unnamed, non-empty expansions give two sources with the same name. -/
theorem unnamed_expansions_collide (idx : Option N → Nat → N) (w : Option W) (r : Bool)
    (v₁ v₂ : V) (vs₁ vs₂ : List V) :
    ∃ a ∈ expandAll idx [.expand none w r (some (v₁ :: vs₁)),
                         .expand none w r (some (v₂ :: vs₂))],
    ∃ b ∈ expandAll idx [.expand none w r (some (v₁ :: vs₁)),
                         .expand none w r (some (v₂ :: vs₂))],
      a.outcome = some v₁ ∧ b.outcome = some v₂ ∧ a.name = b.name := by
  refine ⟨⟨some (idx none 0), w, r, some v₁⟩, ?_, ⟨some (idx none 0), w, r, some v₂⟩, ?_,
    rfl, rfl, rfl⟩
  · simp [expandAll, Entry.expandWith, List.range_succ_eq_map]
  · simp [expandAll, Entry.expandWith, List.range_succ_eq_map]

end Url4Rds
