/-!
# Intent classification

URL4 Spec B §6 gives an intent its mode by its detected value form (Spec B §5.2).
Spec A §1.4.1 says a computed intent must resolve to a prompt or a code pointer.

The model separates two things:

* `IntentForm.specMode` — what the spec says (a pure function of the form);
* `Profile.act` — what a node does. A node may *refuse* an RDS form it cannot run
  (`unsupported_mode`, Spec C §13.5.2); it may never turn an RDS form into a prompt.

`Profile.Conformant` states the rule against Spec B §6. `target` is fully conformant.
`v1` is the owner's choice for url4 2.0 (2026-10-10, Q1): only a relative URI runs as
code; an absolute URI (`url4://`, `https://`, `s3://`, …) keeps the 1.5.1 meaning (it is
fetched and the text is the prompt, as Spec A §1.4.1 "must resolve to a prompt" allows);
a bare token stays a prompt. `v1` therefore deviates from Spec B §6 on exactly three
forms (D1 bare token, D2 absolute URIs), and it never runs code that is not on this node.
-/

namespace Url4Rds

/-- The value form of an intent after Spec B §5.2 detection. -/
inductive IntentForm where
  /-- `'...'` (rule 4). -/
  | quoted
  /-- `/path[?query-tail]` that is not a relative expression (rule 2.3). -/
  | relativeUri
  /-- `url4://node/path[?query]` that is not a remote expression (rule 3.3). -/
  | url4Reference
  /-- any other `scheme://...` (rule 5). -/
  | absoluteUri
  /-- a bare token (rule 10). -/
  | bareToken
  /-- local, relative, remote or iteration expression (rules 1, 2.1, 2.2, 3.1, 3.2). -/
  | expression
  | variableRef
  | selfRef
  | identityRef
  | structObject
  deriving DecidableEq, Repr

/-- The execution mode of an intent. -/
inductive Mode where
  | llm
  | rds
  | computed
  deriving DecidableEq, Repr

/-- Spec B §6 table; forms the table does not list resolve at run time (`computed`). -/
def IntentForm.specMode : IntentForm → Mode
  | .quoted => .llm
  | .relativeUri | .url4Reference | .absoluteUri | .bareToken => .rds
  | .expression | .variableRef | .selfRef | .identityRef | .structObject => .computed

/-- What a node does with an intent. -/
inductive Action where
  /-- LLM mode: the intent text is the prompt. -/
  | prompt
  /-- RDS mode: call the executor mounted at the pointer on this node. -/
  | invokeLocal
  /-- RDS form the node cannot run: fail with `unsupported_mode` (permanent). -/
  | refuse
  /-- Computed: evaluate the intent first, then use the result as a prompt. -/
  | evaluate
  /-- Fetch the URI and use its content as the prompt (the url4 1.5.1 meaning). -/
  | fetchPrompt
  deriving DecidableEq, Repr

/-- An action is allowed for a mode. -/
def Action.conforms : Action → Mode → Bool
  | .prompt, .llm => true
  | .invokeLocal, .rds => true
  | .refuse, .rds => true
  | .evaluate, .computed => true
  | _, _ => false

/-- A node's behavior for every intent form. -/
structure Profile where
  act : IntentForm → Action

/-- A profile is conformant when every form gets an action its spec mode allows. -/
def Profile.Conformant (p : Profile) : Prop :=
  ∀ f : IntentForm, (p.act f).conforms f.specMode = true

/-- url4 2.0: relative code pointers run; absolute URIs are fetched as prompts (D2); bare
tokens stay prompts (D1, deprecated). -/
def v1 : Profile where
  act
    | .quoted => .prompt
    | .relativeUri => .invokeLocal
    | .url4Reference | .absoluteUri => .fetchPrompt
    | .bareToken => .prompt
    | .expression | .variableRef | .selfRef | .identityRef | .structObject => .evaluate

/-- The target profile: a bare token is a named job on this node (Spec B §6). -/
def target : Profile where
  act
    | .quoted => .prompt
    | .relativeUri | .bareToken => .invokeLocal
    | .url4Reference | .absoluteUri => .refuse
    | .expression | .variableRef | .selfRef | .identityRef | .structObject => .evaluate

theorem target_conformant : target.Conformant := by
  intro f
  cases f <;> rfl

/-- `v1` breaks Spec B §6 on the bare token (D1) and the absolute URIs (D2) only. -/
theorem v1_not_conforms_iff (f : IntentForm) :
    (v1.act f).conforms f.specMode = false ↔
      f = .bareToken ∨ f = .url4Reference ∨ f = .absoluteUri := by
  cases f <;> decide

/-- Only a relative URI runs code in `v1`: no code from another node or another scheme
is ever executed. -/
theorem v1_act_eq_invokeLocal_iff (f : IntentForm) :
    v1.act f = .invokeLocal ↔ f = .relativeUri := by
  cases f <;> decide

/-- `v1` and `target` differ only on the three deviating forms. -/
theorem v1_act_eq_target_act (f : IntentForm) (h : (v1.act f).conforms f.specMode = true) :
    v1.act f = target.act f := by
  cases f <;> first | rfl | exact absurd h (by decide)

/-- Field-path strictness (Spec B §5.3.4.1): strict exactly when the node runs the intent
as code. It depends on the profile and the form only, so it is known before resolution,
as the interpolation phase (Spec B §8.2.1) needs. A bare token in `v1` runs as a prompt,
so it stays lenient (LLM mode SHOULD be lenient). -/
def Profile.strictFields (p : Profile) (f : IntentForm) : Bool :=
  p.act f == .invokeLocal

theorem v1_strictFields_iff (f : IntentForm) :
    v1.strictFields f = true ↔ f = .relativeUri := by
  cases f <;> decide

/-- A strict scope is always an RDS scope, in every conformant profile. -/
theorem specMode_eq_rds_of_strictFields (p : Profile) (hp : p.Conformant) (f : IntentForm)
    (h : p.strictFields f = true) : f.specMode = .rds := by
  have hc := hp f
  have ha : p.act f = .invokeLocal := by simpa [Profile.strictFields] using h
  rw [ha] at hc
  cases hm : f.specMode <;> simp_all [Action.conforms]

end Url4Rds
